"""API web (spec mục 9, 10): đăng nhập, CSRF, giới hạn lần sai theo IP, phân quyền, 409, lỗi đúng trường,
OpenAPI chỉ cho admin, cổng HMI chỉ đọc, nhật ký có trước/sau và bộ lọc, luồng SSE."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient

from greenhouse.__main__ import _create_user
from greenhouse.core import db
from greenhouse.core.timeutil import now_ms
from greenhouse.seed import seed
from greenhouse.web.app import create_app
from greenhouse.web.live import Hub
from greenhouse.web.services.overview import compute

ADMIN = ("quantri", "mat-khau-quan-tri")
VIEWER = ("vanhanh", "mat-khau-van-hanh")


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> sqlite3.Connection:
    seed(conn, "sim://api", demo=True)
    _create_user(conn, ADMIN[0], "admin", ADMIN[1], must_change=False)
    _create_user(conn, VIEWER[0], "viewer", VIEWER[1], must_change=False)
    return conn


@pytest.fixture
def client(seeded: sqlite3.Connection) -> Iterator[TestClient]:
    with TestClient(create_app("main")) as c:
        yield c


@pytest.fixture
def hmi(seeded: sqlite3.Connection) -> Iterator[TestClient]:
    with TestClient(create_app("hmi")) as c:
        yield c


def login(c: TestClient, user: tuple[str, str]) -> dict[str, str]:
    """Đăng nhập, trả header CSRF cho các request ghi."""
    c.cookies.clear()
    r = c.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def error(r: Any) -> dict[str, Any]:
    body = r.json()
    assert set(body) == {"error"}, body
    return dict(body["error"])


def device_body(conn: sqlite3.Connection, **over: Any) -> dict[str, Any]:
    tid = conn.execute("SELECT id FROM device_templates WHERE name = 'Node nhiệt ẩm, ánh sáng'").fetchone()[0]
    return {"name": "Node 04", "zone": "Khu B", "connection_id": 1, "unit_id": 4, "template_id": tid, **over}


# --- Đăng nhập ---------------------------------------------------------------------------------


def test_no_default_account(conn: sqlite3.Connection) -> None:
    seed(conn, "sim://x")
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    with TestClient(create_app("main")) as c:
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        assert r.status_code == 401


def test_login_session_cookie_and_me(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"username": "QuanTri ", "password": ADMIN[1]})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "gh_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert "secure" not in cookie  # http thuần khi test; qua Caddy (https) thì có Secure
    me = client.get("/api/auth/me").json()
    assert me["user"]["username"] == "quantri" and me["user"]["role"] == "admin"
    assert me["csrf_token"] == r.json()["csrf_token"]
    assert client.get("/api/auth/site").json()["site_name"] == "Nhà kính demo"


def test_login_limit_five_per_ten_minutes_per_ip(client: TestClient) -> None:
    for left in (4, 3, 2, 1):
        r = client.post("/api/auth/login", json={"username": ADMIN[0], "password": "sai-mat-khau"})
        assert r.status_code == 401
        assert f"Còn {left} lần" in error(r)["message"]
    r = client.post("/api/auth/login", json={"username": "khong-ton-tai", "password": "sai-mat-khau"})
    assert error(r)["code"] == "invalid_credentials"
    r = client.post("/api/auth/login", json={"username": ADMIN[0], "password": ADMIN[1]})
    assert r.status_code == 429
    assert error(r)["code"] == "too_many_attempts"


def test_login_limit_is_per_ip(client: TestClient, seeded: sqlite3.Connection) -> None:
    with db.tx(seeded):
        for _ in range(10):
            seeded.execute(
                "INSERT INTO login_failures(ip, username, ts) VALUES ('192.168.1.50', 'quantri', ?)", (now_ms(),)
            )
    login(client, ADMIN)


def test_concurrent_requests_each_get_own_connection(client: TestClient, seeded: sqlite3.Connection) -> None:
    """Trang Cài đặt gọi 3 endpoint cùng lúc; kết nối SQLite dùng chung giữa các thread từng làm một request
    đọc sai session và trả 401 giả, đẩy người dùng về trang đăng nhập."""
    login(client, ADMIN)
    with db.tx(seeded):
        seeded.execute("UPDATE sessions SET last_seen_at = 0")  # buộc cập nhật phiên (có giao dịch ghi)
    urls = ["/api/admin/settings", "/api/admin/hmi", "/api/admin/audit-log?limit=50", "/api/admin/users"] * 10
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(lambda u: client.get(u).status_code, urls))
    assert codes == [200] * len(urls)


def test_csrf_required_for_writes(client: TestClient) -> None:
    csrf = login(client, ADMIN)
    r = client.post("/api/admin/hmi/reload")
    assert r.status_code == 403 and error(r)["code"] == "csrf"
    r = client.post("/api/admin/hmi/reload", headers={"X-CSRF-Token": "sai"})
    assert r.status_code == 403
    assert client.post("/api/admin/hmi/reload", headers=csrf).status_code == 200


def test_logout_revokes_session(client: TestClient) -> None:
    csrf = login(client, VIEWER)
    assert client.post("/api/auth/logout", headers=csrf).status_code == 200
    assert client.get("/api/overview").status_code == 401


def test_idle_session_expires(client: TestClient, seeded: sqlite3.Connection) -> None:
    login(client, VIEWER)
    with db.tx(seeded):
        seeded.execute("UPDATE sessions SET expires_at = ?", (now_ms() - 1,))
    r = client.get("/api/auth/me")
    assert r.status_code == 401 and error(r)["code"] == "unauthorized"


# --- Phân quyền ----------------------------------------------------------------------------------


def test_viewer_cannot_use_admin_api(client: TestClient, seeded: sqlite3.Connection) -> None:
    csrf = login(client, VIEWER)
    assert client.get("/api/overview").status_code == 200
    assert client.get("/api/devices").status_code == 200
    for method, path in [("GET", "/api/admin/users"), ("GET", "/api/admin/devices"), ("GET", "/api/admin/settings")]:
        r = client.request(method, path)
        assert r.status_code == 403 and error(r)["code"] == "forbidden", path
    r = client.post("/api/admin/devices", json=device_body(seeded), headers=csrf)
    assert r.status_code == 403


def test_openapi_admin_only(client: TestClient) -> None:
    assert client.get("/api/openapi.json").status_code == 401
    assert client.get("/docs").status_code in (404, 503)  # không có Swagger UI công khai
    login(client, VIEWER)
    assert client.get("/api/openapi.json").status_code == 403
    login(client, ADMIN)
    spec = client.get("/api/openapi.json").json()
    assert "/api/readings" in spec["paths"] and "/api/admin/devices" in spec["paths"]
    assert "API v" in client.get("/api/docs").text


def test_temporary_password_must_be_changed(client: TestClient) -> None:
    csrf = login(client, ADMIN)
    r = client.post(
        "/api/admin/users", json={"username": "ky_thuat", "role": "admin", "password": "tam-thoi-123"}, headers=csrf
    )
    assert r.status_code == 201 and r.json()["must_change_password"] is True
    csrf = login(client, ("ky_thuat", "tam-thoi-123"))
    r = client.get("/api/admin/devices")
    assert r.status_code == 403 and error(r)["code"] == "password_change_required"
    r = client.post("/api/auth/password", json={"current": "tam-thoi-123", "new": "ngan"}, headers=csrf)
    assert error(r)["field"] == "new"
    r = client.post("/api/auth/password", json={"current": "tam-thoi-123", "new": "mat-khau-moi-dai"}, headers=csrf)
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is False
    assert client.get("/api/admin/devices").status_code == 200


def test_cannot_lock_last_admin(client: TestClient, seeded: sqlite3.Connection) -> None:
    csrf = login(client, ADMIN)
    uid = seeded.execute("SELECT id FROM users WHERE username = ?", (ADMIN[0],)).fetchone()[0]
    r = client.patch(f"/api/admin/users/{uid}", json={"is_active": False}, headers=csrf)
    assert r.status_code == 409 and error(r)["code"] == "last_admin"


def test_locking_user_revokes_sessions(client: TestClient, seeded: sqlite3.Connection) -> None:
    csrf = login(client, ADMIN)
    uid = seeded.execute("SELECT id FROM users WHERE username = ?", (VIEWER[0],)).fetchone()[0]
    seeded.execute(
        "INSERT INTO sessions(token_hash, user_id, csrf_token, created_at, last_seen_at, expires_at) "
        "VALUES ('x', ?, 'y', 0, 0, ?)",
        (uid, now_ms() + 10**9),
    )
    assert client.patch(f"/api/admin/users/{uid}", json={"is_active": False}, headers=csrf).status_code == 200
    assert seeded.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (uid,)).fetchone()[0] == 0


# --- Cấu hình: 409, lỗi đúng trường ---------------------------------------------------------------


def test_duplicate_unit_id_is_409(client: TestClient, seeded: sqlite3.Connection) -> None:
    csrf = login(client, ADMIN)
    r = client.post("/api/admin/devices", json=device_body(seeded, unit_id=2), headers=csrf)
    assert r.status_code == 409
    assert error(r) | {"message": ""} == {"code": "duplicate_unit_id", "field": "unit_id", "message": ""}
    r = client.post("/api/admin/devices", json=device_body(seeded), headers=csrf)
    assert r.status_code == 201
    new = r.json()
    assert [c["key"] for c in new["channels"]] == ["temperature", "humidity", "illuminance"]
    r = client.patch(f"/api/admin/devices/{new['id']}", json=device_body(seeded, unit_id=3), headers=csrf)
    assert r.status_code == 409 and error(r)["code"] == "duplicate_unit_id"
    # Xóa mềm rồi dùng lại unit ID được
    assert client.delete(f"/api/admin/devices/{new['id']}", headers=csrf).status_code == 200
    assert client.post("/api/admin/devices", json=device_body(seeded), headers=csrf).status_code == 201


def test_delete_in_use_is_409(client: TestClient, seeded: sqlite3.Connection) -> None:
    csrf = login(client, ADMIN)
    tid = seeded.execute("SELECT id FROM device_templates WHERE name = 'Node tốc độ gió'").fetchone()[0]
    r = client.delete(f"/api/admin/templates/{tid}", headers=csrf)
    assert r.status_code == 409 and error(r)["code"] == "in_use"
    r = client.delete("/api/admin/connections/1", headers=csrf)
    assert r.status_code == 409 and error(r)["code"] == "in_use"
    did = seeded.execute("SELECT id FROM devices WHERE template_id = ?", (tid,)).fetchone()[0]
    assert client.delete(f"/api/admin/devices/{did}", headers=csrf).status_code == 200
    assert client.delete(f"/api/admin/templates/{tid}", headers=csrf).status_code == 200
    # Dữ liệu lịch sử của thiết bị đã xóa mềm vẫn còn
    assert seeded.execute("SELECT COUNT(*) FROM channels WHERE device_id = ?", (did,)).fetchone()[0] == 1


def test_field_level_errors(client: TestClient, seeded: sqlite3.Connection) -> None:
    csrf = login(client, ADMIN)
    r = client.post("/api/admin/devices", json=device_body(seeded, name=""), headers=csrf)
    assert r.status_code == 400 and error(r)["field"] == "name"
    body = device_body(seeded, channels=[{"key": "temperature", "alarm_low": 30, "alarm_high": 20}])
    r = client.post("/api/admin/devices", json=body, headers=csrf)
    assert error(r)["field"] == "channels.temperature.alarm_high"
    body = device_body(seeded, channels=[{"key": "humidity", "display_min": -10}])
    r = client.post("/api/admin/devices", json=body, headers=csrf)
    assert error(r)["field"] == "channels.humidity.display_min"
    tpl = {
        "name": "Mẫu thử",
        "category": "climate",
        "channels": [
            {
                "key": "t",
                "label": "T",
                "fc": 4,
                "address": 0,
                "type": "float32",
                "byte_order": "ABCD",
                "min": 0,
                "max": 50,
                "display_max": 60,
            }
        ],
    }
    r = client.post("/api/admin/templates", json=tpl, headers=csrf)
    assert r.status_code == 400 and error(r)["field"] == "channels.0.display_max"
    tpl["channels"][0]["key"] = "Sai Key"  # type: ignore[index]
    r = client.post("/api/admin/templates", json=tpl, headers=csrf)
    assert error(r)["field"] == "channels.0.key"
    r = client.put("/api/admin/settings", json={"backup_time": "25:00"}, headers=csrf)
    assert r.status_code == 400 and error(r)["field"] == "backup_time"
    r = client.post(
        "/api/admin/connections", json={"name": "Bus 2", "type": "rtu", "params": {"port": "sim://api"}}, headers=csrf
    )
    assert r.status_code == 409 and error(r)["field"] == "params.port"
    r = client.post(
        "/api/admin/connections",
        json={"name": "Bus 2", "type": "rtu", "params": {"port": "/dev/x", "baudrate": 1234}},
        headers=csrf,
    )
    assert r.status_code == 400 and error(r)["field"] == "params.baudrate"


def test_template_roundtrip_export_import(client: TestClient, seeded: sqlite3.Connection) -> None:
    csrf = login(client, ADMIN)
    tid = seeded.execute("SELECT id FROM device_templates WHERE name = 'Node nhiệt ẩm, ánh sáng'").fetchone()[0]
    r = client.get(f"/api/admin/templates/{tid}?download=1")
    assert "attachment" in r.headers["content-disposition"]
    exported = r.json()
    assert exported["channels"][0] == {
        "key": "temperature",
        "label": "Nhiệt độ",
        "unit": "°C",
        "fc": 4,
        "address": 0,
        "type": "float32",
        "byte_order": "ABCD",
        "scale": 1.0,
        "offset": 0.0,
        "min": -40.0,
        "max": 80.0,
        "display_min": 0.0,
        "display_max": 50.0,
        "agg": "mean",
        "estimate": False,
        "note": "",
    }
    r = client.post("/api/admin/templates/import", json=exported, headers=csrf)
    assert r.status_code == 201 and r.json()[0]["name"] == "Node nhiệt ẩm, ánh sáng (nhập)"


def test_collector_offline_message(client: TestClient, seeded: sqlite3.Connection) -> None:
    csrf = login(client, ADMIN)
    r = client.post(
        "/api/admin/devices/test-read", json={"connection_id": 1, "unit_id": 2, "template_id": 2}, headers=csrf
    )
    assert r.status_code == 503
    assert error(r)["code"] == "collector_offline"
    assert "Cấu hình vẫn lưu được" in error(r)["message"]
    # Lưu cấu hình vẫn được khi collector dừng
    assert client.post("/api/admin/devices", json=device_body(seeded), headers=csrf).status_code == 201


def test_audit_log_before_after_and_filters(client: TestClient, seeded: sqlite3.Connection) -> None:
    csrf = login(client, ADMIN)
    did = seeded.execute("SELECT id FROM devices WHERE unit_id = 2").fetchone()[0]
    dev = client.get(f"/api/admin/devices/{did}").json()
    body = {
        k: dev[k] for k in ("name", "zone", "connection_id", "unit_id", "template_id", "poll_interval_s", "enabled")
    }
    body["channels"] = [
        {
            "key": "temperature",
            "label": "Nhiệt độ trong nhà",
            "display_min": 10,
            "display_max": 40,
            "alarm_low": 16,
            "alarm_high": 35,
        }
    ]
    r = client.patch(f"/api/admin/devices/{did}", json=body, headers=csrf)
    assert r.status_code == 200, r.text
    log = client.get("/api/admin/audit-log", params={"entity": "device", "user": ADMIN[0]}).json()
    [row] = log["rows"]
    assert "ngưỡng 18–32 → 16–35 °C" in row["summary"]
    assert "Nhiệt độ: nhãn → Nhiệt độ trong nhà" in row["summary"]
    before, after = json.loads(row["before"]), json.loads(row["after"])
    assert before["channels"]["temperature"]["alarm_high"] == 32
    assert after["channels"]["temperature"]["alarm_high"] == 35
    assert ADMIN[0] in log["users"] and "device" in log["entities"]
    assert client.get("/api/admin/audit-log", params={"user": VIEWER[0]}).json()["rows"] == []
    assert len(client.get("/api/admin/audit-log", params={"entity": "seed"}).json()["rows"]) == 1


# --- Dữ liệu -------------------------------------------------------------------------------------


def test_readings_and_csv(client: TestClient, seeded: sqlite3.Connection) -> None:
    cid = seeded.execute("SELECT id FROM channels WHERE key = 'temperature'").fetchone()[0]
    t0 = now_ms() - 3_600_000
    with db.tx(seeded):
        seeded.executemany(
            "INSERT INTO readings(channel_id, ts, value, quality) VALUES (?, ?, ?, 0)",
            [(cid, t0 + i * 10_000, 25.0 + i % 5) for i in range(300)],
        )
    login(client, VIEWER)
    r = client.get("/api/readings", params={"channels": str(cid), "from": t0, "to": t0 + 3_600_000})
    assert r.status_code == 200
    [s] = r.json()["series"]
    assert len(s["points"]) == 300 and s["stats"] == {"min": 25.0, "max": 29.0, "avg": 27.0}
    r = client.get("/api/readings", params={"channels": "", "from": t0, "to": t0 + 1})
    assert error(r)["field"] == "channels"
    r = client.get("/api/readings", params={"channels": str(cid), "from": t0, "to": t0 - 1})
    assert error(r)["field"] == "to"
    r = client.get(
        "/api/export.csv", params={"channels": str(cid), "from": t0, "to": t0 + 3_600_000, "resolution": "5m"}
    )
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text.startswith("﻿timestamp,")
    assert len(r.text.strip().splitlines()) >= 13
    spark = client.get("/api/sparklines").json()
    assert spark["bucket_ms"] == 60_000
    line = spark["channels"][str(cid)]
    assert 45 <= len(line["points"]) <= 61 and (line["min"], line["max"]) == (25.0, 29.0)
    est = client.get("/api/export/estimate", params={"channels": str(cid), "from": t0, "to": t0 + 3_600_000}).json()
    assert est["raw"] == 300


def test_overview_snapshot_shape(client: TestClient) -> None:
    login(client, VIEWER)
    snap = client.get("/api/overview").json()
    assert snap["collector"] == {"online": False, "waiting": False}
    assert {c["key"] for c in snap["channels"]} == {"wind_speed", "temperature", "humidity", "illuminance", "co2"}
    assert all(c["state"] == "nodata" for c in snap["channels"])
    [vpd] = snap["derived"]
    assert (vpd["display_min"], vpd["display_max"]) == (0.0, 2.5)
    assert next(c for c in snap["channels"] if c["key"] == "co2")["estimate"] is True


def test_errors_use_common_format(client: TestClient) -> None:
    r = client.get("/api/khong-co")
    assert r.status_code == 404 and error(r)["code"] == "not_found"


# --- Cổng HMI ------------------------------------------------------------------------------------


def test_hmi_port_is_read_only_without_login(hmi: TestClient) -> None:
    r = hmi.get("/api/hmi/overview")
    assert r.status_code == 200
    snap = r.json()
    assert snap["hmi"]["layout"] == "cards"
    assert snap["hmi"]["cards"][0]["id"].startswith("ch:")
    assert any(c["id"] == "system" for c in snap["hmi"]["cards"])
    assert all(not c["visible"] for c in snap["hmi"]["cards"] if c["id"].startswith("vpd:"))  # VPD mặc định tắt
    assert hmi.post("/api/hmi/overview").status_code == 405
    assert error(hmi.post("/api/auth/login", json={}))["code"] == "read_only"
    assert hmi.get("/api/admin/users").status_code == 404
    assert hmi.get("/api/overview").status_code == 404
    assert hmi.get("/api/openapi.json").status_code == 404


def test_hmi_page_only_on_hmi_port(client: TestClient, hmi: TestClient) -> None:
    assert client.get("/hmi").status_code == 404
    assert hmi.get("/hmi").status_code == 503  # chưa build frontend trong test
    assert hmi.get("/", follow_redirects=False).headers["location"] == "/hmi"


def test_hmi_settings_apply(client: TestClient, seeded: sqlite3.Connection) -> None:
    csrf = login(client, ADMIN)
    cfg = client.get("/api/admin/hmi").json()
    cards = [{"id": c["id"], "visible": c["id"] != "system"} for c in reversed(cfg["cards"])]
    r = client.put("/api/admin/hmi", json={"layout": "overview", "cards": cards, "allow_charts": False}, headers=csrf)
    assert r.status_code == 200
    assert r.json()["layout"] == "overview"
    with TestClient(create_app("hmi")) as h:
        snap = h.get("/api/hmi/overview").json()
        assert snap["hmi"]["layout"] == "overview"
        assert [c["id"] for c in snap["hmi"]["cards"]] == [c["id"] for c in cards]
        cid = seeded.execute("SELECT id FROM channels LIMIT 1").fetchone()[0]
        r = h.get("/api/hmi/readings", params={"channels": str(cid), "from": 0, "to": 1000})
        assert r.status_code == 403 and error(r)["code"] == "charts_disabled"
        assert h.get("/api/hmi/sparklines").status_code == 200  # xu hướng trên thẻ không phụ thuộc quyền xem biểu đồ
    log = client.get("/api/admin/audit-log", params={"entity": "hmi"}).json()["rows"]
    assert "bố cục Tổng quan" in log[0]["summary"]


# --- Luồng SSE: chỉ đẩy phần thay đổi ------------------------------------------------------------


def test_sse_diff_events(seeded: sqlite3.Connection) -> None:
    old = compute(seeded, None)
    cid = old["channels"][0]["id"]
    with db.tx(seeded):
        seeded.execute(
            "INSERT INTO channel_latest(channel_id, ts, value, quality) VALUES (?, ?, 3.4, 'good')", (cid, now_ms())
        )
    new = compute(seeded, {"last_commit_at": now_ms(), "workers": []})
    events = Hub.diff(old, new)
    kinds = [e.split("\n", 1)[0] for e in events]
    assert kinds == ["event: reading", "event: system"]
    data = json.loads(events[0].split("data: ", 1)[1])
    assert data["id"] == cid and data["value"] == 3.4 and data["state"] == "ok"
    # Thêm thiết bị: đổi cấu trúc thì gửi lại snapshot
    with db.tx(seeded):
        seeded.execute("UPDATE devices SET deleted_at = 1 WHERE unit_id = 3")
    assert Hub.diff(new, compute(seeded, None))[0].startswith("event: snapshot")
    # HMI: đổi cấu hình và nút tải lại
    a = {**new, "hmi": {"layout": "cards", "reload_token": ""}}
    b = {**new, "hmi": {"layout": "overview", "reload_token": "abc"}}
    kinds = [e.split("\n", 1)[0] for e in Hub.diff(a, b)]
    assert kinds == ["event: reload", "event: hmi_config"]

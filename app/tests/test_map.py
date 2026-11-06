"""Bản đồ trại (docs/spec-ban-do.md): tọa độ trong cài đặt, /api/map/*, đọc file theo Range, cổng HMI, install-map."""

from __future__ import annotations

import argparse
import sqlite3
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from greenhouse.__main__ import PMTILES_HEADER_SIZE, _create_user, cmd_install_map
from greenhouse.core import config, db
from greenhouse.web.app import CSP, create_app

ADMIN = ("quantri", "mat-khau-quan-tri")
VIEWER = ("vanhanh", "mat-khau-van-hanh")


def pmtiles_bytes(tile_data: bytes = b"t" * 2048) -> bytes:
    """File PMTiles v3 tối thiểu: đủ header để install-map kiểm tra; khối tile nằm ngay sau header."""
    head = bytearray(PMTILES_HEADER_SIZE)
    head[:8] = b"PMTiles\x03"
    struct.pack_into("<QQ", head, 56, PMTILES_HEADER_SIZE, len(tile_data))
    return bytes(head) + tile_data


@pytest.fixture
def users(conn: sqlite3.Connection) -> sqlite3.Connection:
    _create_user(conn, ADMIN[0], "admin", ADMIN[1], must_change=False)
    _create_user(conn, VIEWER[0], "viewer", VIEWER[1], must_change=False)
    return conn


@pytest.fixture
def client(users: sqlite3.Connection) -> Iterator[TestClient]:
    with TestClient(create_app("main")) as c:
        yield c


def login(c: TestClient, user: tuple[str, str]) -> dict[str, str]:
    c.cookies.clear()
    r = c.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def install(data: bytes | None = None) -> bytes:
    p = config.basemap_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = pmtiles_bytes() if data is None else data
    p.write_bytes(data)
    return data


def put(c: TestClient, csrf: dict[str, str], **body: Any) -> Any:
    return c.put("/api/admin/settings", json=body, headers=csrf)


def last_audit(conn: sqlite3.Connection) -> sqlite3.Row:
    return conn.execute("SELECT * FROM audit_log WHERE entity = 'settings' ORDER BY id DESC LIMIT 1").fetchone()


def test_config_before_deployment(client: TestClient) -> None:
    assert client.get("/api/map/config").status_code == 401
    login(client, VIEWER)
    assert client.get("/api/map/config").json() == {"site": None, "basemap": None}
    assert client.get("/api/map/basemap.pmtiles").status_code == 404


def test_set_edit_clear_location(client: TestClient, conn: sqlite3.Connection) -> None:
    csrf = login(client, ADMIN)
    r = put(client, csrf, site_lat=11.94, site_lng=108.44)
    assert r.status_code == 200 and (r.json()["site_lat"], r.json()["site_lng"]) == (11.94, 108.44)
    login(client, VIEWER)
    site = client.get("/api/map/config").json()["site"]
    assert site == {"name": db.get_setting(conn, "site_name"), "lat": 11.94, "lng": 108.44}

    csrf = login(client, ADMIN)
    assert put(client, csrf, site_lat=11.95, site_lng=108.45).status_code == 200
    row = last_audit(conn)
    assert '"site_lat": 11.94' in row["before"] and '"site_lat": 11.95' in row["after"]
    assert "Vĩ độ trại" in row["summary"]

    r = put(client, csrf, clear_site_location=True)
    assert r.status_code == 200 and r.json()["site_lat"] is None and r.json()["site_lng"] is None
    assert client.get("/api/map/config").json()["site"] is None
    row = last_audit(conn)
    assert '"site_lat": 11.95' in row["before"] and '"site_lat": null' in row["after"]


def test_partial_save_keeps_location_and_audit_is_accurate(client: TestClient, conn: sqlite3.Connection) -> None:
    csrf = login(client, ADMIN)
    put(client, csrf, site_lat=11.94, site_lng=108.44)
    assert put(client, csrf, backup_keep=9).status_code == 200
    assert db.get_setting(conn, "site_lat") == 11.94
    assert "độ trại" not in last_audit(conn)["summary"]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"site_lat": 91, "site_lng": 108}, "site_lat"),
        ({"site_lat": -91, "site_lng": 108}, "site_lat"),
        ({"site_lat": 11, "site_lng": 181}, "site_lng"),
        ({"site_lat": 11}, "site_lng"),
        ({"site_lng": 108}, "site_lat"),
    ],
)
def test_invalid_location(client: TestClient, conn: sqlite3.Connection, body: dict[str, Any], field: str) -> None:
    csrf = login(client, ADMIN)
    r = put(client, csrf, **body)
    assert r.status_code == 400 and r.json()["error"]["field"] == field
    assert db.get_setting(conn, "site_lat") is None


def test_viewer_cannot_set_location(client: TestClient) -> None:
    csrf = login(client, VIEWER)
    assert put(client, csrf, site_lat=11, site_lng=108).status_code == 403


def test_public_site_endpoint_hides_location(client: TestClient) -> None:
    csrf = login(client, ADMIN)
    put(client, csrf, site_lat=11.94, site_lng=108.44)
    client.cookies.clear()
    r = client.get("/api/auth/site")
    assert r.status_code == 200 and set(r.json()) == {"site_name"}


def test_basemap_range(client: TestClient) -> None:
    data = install()
    assert client.get("/api/map/basemap.pmtiles").status_code == 401
    login(client, VIEWER)
    assert client.get("/api/map/config").json()["basemap"] == {
        "url": "/api/map/basemap.pmtiles",
        "size_bytes": len(data),
    }
    r = client.get("/api/map/basemap.pmtiles", headers={"Range": "bytes=0-126"})
    assert r.status_code == 206 and r.content == data[:127]
    assert r.headers["content-range"] == f"bytes 0-126/{len(data)}"
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["cache-control"] == "private, max-age=86400"
    assert r.headers["etag"] and "content-encoding" not in r.headers


def test_csp_unchanged_on_map_routes(client: TestClient) -> None:
    login(client, VIEWER)
    assert client.get("/api/map/config").headers["content-security-policy"] == CSP


def test_spa_route_and_static_only_on_main(users: sqlite3.Connection) -> None:
    dist = config.frontend_dist()
    (dist / "map").mkdir(parents=True)
    (dist / "map" / "a.json").write_text("{}", encoding="utf-8")
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    install()
    with TestClient(create_app("main")) as c:
        assert c.get("/ban-do").status_code == 200
        r = c.get("/map/a.json")
        assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=604800"
    with TestClient(create_app("hmi")) as h:
        for path in ("/ban-do", "/map/a.json", "/api/map/config", "/api/map/basemap.pmtiles"):
            assert h.get(path).status_code == 404, path


def run_install(path: Path) -> None:
    cmd_install_map(argparse.Namespace(file=str(path)))


def test_install_map(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "moi.pmtiles"
    data = pmtiles_bytes()
    src.write_bytes(data)
    run_install(src)
    assert config.basemap_path().read_bytes() == data
    assert "Đã cài bản đồ" in capsys.readouterr().out
    assert [p.name for p in config.basemap_path().parent.iterdir()] == ["basemap.pmtiles"]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"khong phai pmtiles" * 20, "không phải file PMTiles"),
        (b"PMTiles\x02" + bytes(200), "không phải file PMTiles"),
        (b"PMTiles\x03", "không phải file PMTiles"),
        (pmtiles_bytes()[:500], "thiếu dữ liệu"),
    ],
)
def test_install_map_rejects_bad_file_and_keeps_current(tmp_path: Path, content: bytes, message: str) -> None:
    current = install()
    src = tmp_path / "sai.pmtiles"
    src.write_bytes(content)
    with pytest.raises(SystemExit) as e:
        run_install(src)
    assert message in str(e.value) and "giữ nguyên" in str(e.value)
    assert config.basemap_path().read_bytes() == current


def test_install_map_missing_source(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as e:
        run_install(tmp_path / "khong-co.pmtiles")
    assert "Không đọc được" in str(e.value)


def test_map_appears_without_restart(client: TestClient, tmp_path: Path) -> None:
    """File cài sau khi app đã chạy vẫn dùng được ngay."""
    login(client, VIEWER)
    assert client.get("/api/map/config").json()["basemap"] is None
    src = tmp_path / "moi.pmtiles"
    src.write_bytes(pmtiles_bytes())
    run_install(src)
    assert client.get("/api/map/config").json()["basemap"] is not None
    assert client.get("/api/map/basemap.pmtiles", headers={"Range": "bytes=0-7"}).content == b"PMTiles\x03"

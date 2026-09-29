"""Chẩn đoán (8.6), cài đặt, nhật ký, backup, màn hình HMI (8.7)."""

from __future__ import annotations

import re
import secrets
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ...collector import maintenance
from ...core import config, db
from ...core.errors import invalid, not_found
from ...core.timeutil import now_ms
from .. import collector_client
from ..auditfmt import diff
from ..auth import User, get_async_db, get_db, require_admin
from ..live import hmi_presence
from ..services.hmi import effective_cards, hmi_config
from ..services.overview import collector_info, compute

router = APIRouter(prefix="/api/admin", tags=["Hệ thống"])

TIMEZONES = ["Asia/Ho_Chi_Minh", "Asia/Bangkok", "Asia/Jakarta", "Asia/Singapore", "UTC"]
KIND_NAMES = {"timeout": "Timeout", "crc": "CRC", "exception": "Exception", "sensor": "Lỗi cảm biến", "io": "Lỗi cổng"}


# --- Chẩn đoán ----------------------------------------------------------------------------


def _cpu_temp() -> float | None:
    try:
        return round(int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000, 1)
    except (OSError, ValueError):
        return None


def _has_rtc() -> bool:
    return Path("/dev/rtc0").exists()


def _db_size() -> int:
    total = 0
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(config.db_path()) + suffix)
        if p.exists():
            total += p.stat().st_size
    return total


@router.get("/diagnostics")
async def diagnostics(
    user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_async_db)
) -> dict[str, Any]:
    status = await collector_client.status(fresh=True)
    now = now_ms()
    snap = compute(conn, status)
    try:
        free = shutil.disk_usage(config.data_dir()).free
    except OSError:
        free = None
    totals = dict.fromkeys(KIND_NAMES, 0)
    devices = []
    for d in snap["devices"]:

        def stats(since: int, did: int = d["id"]) -> dict[str, Any]:
            r = conn.execute(
                "SELECT COALESCE(SUM(requests), 0), COALESCE(SUM(ok), 0), COALESCE(SUM(timeout), 0), COALESCE(SUM(crc), 0), "
                "COALESCE(SUM(exception), 0), COALESCE(SUM(sensor), 0), COALESCE(SUM(io), 0), COALESCE(SUM(rtt_sum), 0), "
                "COALESCE(SUM(rtt_n), 0) FROM device_stats_5m WHERE device_id = ? AND ts >= ?",
                (did, since // 300_000 * 300_000),
            ).fetchone()
            return dict(
                zip(
                    ["requests", "ok", "timeout", "crc", "exception", "sensor", "io", "rtt_sum", "rtt_n"],
                    r,
                    strict=True,
                )
            )

        s1, s24 = stats(now - 3_600_000), stats(now - 86_400_000)
        for k in totals:
            totals[k] += s24[k]
        st = db.row(conn.execute("SELECT * FROM device_status WHERE device_id = ?", (d["id"],))) or {}
        devices.append(
            {
                **d,
                "errors_1h": s1["requests"] - s1["ok"],
                "requests_1h": s1["requests"],
                "errors_24h": s24["requests"] - s24["ok"],
                "requests_24h": s24["requests"],
                "avg_rtt_ms": round(s24["rtt_sum"] / s24["rtt_n"], 1) if s24["rtt_n"] else None,
                "last_error": st.get("last_error"),
                "last_error_kind": st.get("last_error_kind"),
                "last_error_ts": st.get("last_error_ts"),
            }
        )
    events = db.rows(
        conn.execute(
            "SELECT e.*, d.name AS device_name FROM device_events e LEFT JOIN devices d ON d.id = e.device_id "
            "ORDER BY e.id DESC LIMIT 20"
        )
    )
    connections = [
        {
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "worker": next((w for w in (status or {}).get("workers", []) if w["connection_id"] == r["id"]), None),
        }
        for r in conn.execute("SELECT id, name, type FROM connections ORDER BY id")
    ]
    return {
        "now": now,
        "collector": collector_info(status),
        "system": {
            "free_bytes": free,
            "db_bytes": _db_size(),
            "last_backup": db.get_setting(conn, "last_backup"),
            "cpu_temp": _cpu_temp(),
            "clock_synced": (status or {}).get("clock_synced"),
            "rtc": _has_rtc(),
        },
        "devices": devices,
        "errors_24h": totals,
        "events": events,
        "connections": connections,
    }


# --- Cài đặt ------------------------------------------------------------------------------


class SettingsIn(BaseModel):
    site_name: str | None = Field(None, min_length=1, max_length=60)
    timezone: str | None = None
    public_url: str | None = Field(None, max_length=200)
    raw_retention_days: int | None = Field(None, ge=30, le=3650)
    backup_time: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    backup_keep: int | None = Field(None, ge=1, le=60)


SETTING_LABELS = {
    "site_name": "Tên site",
    "timezone": "Múi giờ",
    "public_url": "Địa chỉ web app",
    "raw_retention_days": "Giữ dữ liệu thô (ngày)",
    "backup_time": "Giờ backup",
    "backup_keep": "Số bản backup giữ lại",
}


@router.get("/settings")
def get_settings(user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    s = db.get_settings(conn)
    return {
        **{k: s[k] for k in SETTING_LABELS},
        "timezones": TIMEZONES,
        "last_backup": s.get("last_backup"),
        "backup_dir": str(config.backup_dir()),
    }


@router.put("/settings")
def put_settings(
    body: SettingsIn, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    new = body.model_dump(exclude_none=True)
    if "timezone" in new and new["timezone"] not in TIMEZONES:
        raise invalid("Múi giờ không hỗ trợ", "timezone")
    if "public_url" in new:
        new["public_url"] = new["public_url"].strip()
        if new["public_url"] and not re.match(r"^https?://[^\s/]+", new["public_url"]):
            raise invalid("Địa chỉ phải bắt đầu bằng https:// hoặc http://", "public_url")
    old = db.get_settings(conn)
    changes = diff(old, new, SETTING_LABELS)
    with db.tx(conn):
        for k, v in new.items():
            db.set_setting(conn, k, v)
        if changes:
            db.audit(conn, user.ref, "update", "settings", None, {k: old.get(k) for k in new}, new, "; ".join(changes))
    return get_settings(user, conn)


# --- Nhật ký thay đổi -------------------------------------------------------------------


@router.get("/audit-log", summary="Lọc theo người dùng và đối tượng")
def audit_log(
    user_name: str | None = Query(None, alias="user"),
    entity: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    before: int | None = None,
    user: User = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    sql, args = "SELECT * FROM audit_log WHERE 1 = 1", list[Any]()
    if user_name:
        sql += " AND username = ?"
        args.append(user_name)
    if entity:
        sql += " AND entity = ?"
        args.append(entity)
    if before:
        sql += " AND id < ?"
        args.append(before)
    rows = db.rows(conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, limit)))
    users = [
        r[0] for r in conn.execute("SELECT DISTINCT username FROM audit_log WHERE username IS NOT NULL ORDER BY 1")
    ]
    entities = [r[0] for r in conn.execute("SELECT DISTINCT entity FROM audit_log ORDER BY 1")]
    return {"rows": rows, "users": users, "entities": entities}


# --- Backup -------------------------------------------------------------------------------


@router.post("/backup", summary="Backup ngay bằng VACUUM INTO")
def backup_now(user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    info = maintenance.run_backup(config.db_path())
    with db.tx(conn):
        db.audit(conn, user.ref, "backup", "settings", None, None, info, f"Backup thủ công {info['file']}")
    return info


@router.get("/backup/latest", summary="Tải bản backup mới nhất")
def download_backup(user: User = Depends(require_admin)) -> FileResponse:
    p = maintenance.latest_backup()
    if p is None:
        raise not_found("Chưa có bản backup nào")
    return FileResponse(p, media_type="application/octet-stream", filename=p.name)


# --- Màn hình HMI -------------------------------------------------------------------------


class HmiCard(BaseModel):
    id: str = Field(max_length=80)
    visible: bool = True


class HmiIn(BaseModel):
    layout: Literal["cards", "overview"] | None = None
    cards: list[HmiCard] | None = None
    allow_charts: bool | None = None


def _hmi(request: Request, conn: sqlite3.Connection) -> dict[str, Any]:
    snap = compute(conn, None)
    cfg = hmi_config(conn, snap)
    labels: dict[str, dict[str, Any]] = {"system": {"label": "Hệ thống", "sub": "đồng hồ, cảnh báo"}}
    for c in snap["channels"]:
        labels[f"ch:{c['id']}"] = {"label": c["label"], "sub": c["zone"] + (" · ước tính" if c["estimate"] else "")}
    for d in snap["derived"]:
        labels[d["id"]] = {"label": "VPD", "sub": f"{d['zone']} · tính toán"}
    p = hmi_presence()
    return {
        **cfg,
        "cards": [{**c, **labels.get(c["id"], {"label": c["id"], "sub": ""})} for c in cfg["cards"]],
        "url": f"http://{config.HMI_HOST}:{config.HMI_PORT}/hmi",
        "status": {
            "online": p is not None,
            "connected_since": p["connected_since"] if p else None,
            "width": p["width"] if p else None,
            "height": p["height"] if p else None,
            "kiosk": "Chrome" in (p["user_agent"] if p else ""),
        },
    }


@router.get("/hmi")
def get_hmi(
    request: Request, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    return _hmi(request, conn)


@router.put("/hmi", summary="Bố cục, thẻ và thứ tự, cho xem biểu đồ; áp dụng ngay qua SSE")
def put_hmi(
    body: HmiIn, request: Request, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    old = db.get_settings(conn)
    changes = []
    with db.tx(conn):
        if body.layout is not None and body.layout != old["hmi_layout"]:
            db.set_setting(conn, "hmi_layout", body.layout)
            changes.append("bố cục " + ("HMI thẻ lớn" if body.layout == "cards" else "Tổng quan"))
        if body.cards is not None:
            cards = [c.model_dump() for c in body.cards]
            db.set_setting(conn, "hmi_cards", cards)
            if cards != effective_cards(old, compute(conn, None)):
                changes.append("thẻ hoặc thứ tự thẻ")
        if body.allow_charts is not None and body.allow_charts != old["hmi_allow_charts"]:
            db.set_setting(conn, "hmi_allow_charts", body.allow_charts)
            changes.append("cho xem biểu đồ" if body.allow_charts else "tắt biểu đồ")
        if changes:
            db.audit(
                conn,
                user.ref,
                "update",
                "hmi",
                None,
                None,
                body.model_dump(exclude_none=True),
                "Màn hình HMI: đổi " + ", ".join(changes),
            )
    return _hmi(request, conn)


@router.post("/hmi/reload", summary="Gửi sự kiện reload tới trang HMI")
def reload_hmi(user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, bool]:
    with db.tx(conn):
        db.set_setting(conn, "hmi_reload_token", secrets.token_hex(6))
        db.audit(conn, user.ref, "reload", "hmi", None, None, None, "Tải lại màn hình HMI")
    return {"ok": True}

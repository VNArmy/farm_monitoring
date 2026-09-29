"""Thiết bị (spec mục 4.3, 8.4): trùng unit ID trả 409, xóa mềm, thang hiển thị và ngưỡng từng kênh, đọc thử."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...core import db
from ...core.errors import conflict, invalid, not_found
from ...core.models import ChannelDef, DeviceIn, validate_device_channel
from ...core.repo import sync_device_channels, template_def
from ...core.timeutil import now_ms
from .. import collector_client
from ..auditfmt import diff, rng
from ..auth import User, get_async_db, get_db, require_admin

router = APIRouter(prefix="/api/admin/devices", tags=["Thiết bị"])


def _channels(conn: sqlite3.Connection, did: int, template_id: int) -> list[dict[str, Any]]:
    tdef = template_def(conn, template_id)
    by_key = {c.key: c for c in tdef.channels} if tdef else {}
    out = []
    for r in db.rows(
        conn.execute(
            "SELECT ch.*, cl.value, cl.ts, cl.quality FROM channels ch LEFT JOIN channel_latest cl ON cl.channel_id = ch.id "
            "WHERE ch.device_id = ? ORDER BY ch.id",
            (did,),
        )
    ):
        c = by_key.get(r["key"])
        if c is None:
            continue
        lo, hi = c.effective_display()
        r["enabled"] = bool(r["enabled"])
        r["template"] = {
            "label": c.label,
            "display_min": lo,
            "display_max": hi,
            "min": c.min,
            "max": c.max,
            "decimals": c.effective_decimals(),
            "order": tdef.channels.index(c) if tdef else 0,
        }
        out.append(r)
    out.sort(key=lambda r: r["template"]["order"])
    return out


def _out(conn: sqlite3.Connection, d: dict[str, Any]) -> dict[str, Any]:
    d = dict(d)
    d["enabled"] = bool(d["enabled"])
    d["channels"] = _channels(conn, d["id"], d["template_id"])
    return d


_LIST = (
    "SELECT d.*, t.name AS template_name, c.name AS connection_name, c.type AS connection_type, ds.state, ds.since, "
    "ds.last_ok_ts, ds.last_rtt_ms, ds.consecutive_failures, ds.last_error, ds.last_error_kind, ds.last_error_ts "
    "FROM devices d LEFT JOIN device_templates t ON t.id = d.template_id LEFT JOIN connections c ON c.id = d.connection_id "
    "LEFT JOIN device_status ds ON ds.device_id = d.id WHERE d.deleted_at IS NULL"
)


def _load(conn: sqlite3.Connection, did: int) -> dict[str, Any]:
    r = db.row(conn.execute(_LIST + " AND d.id = ?", (did,)))
    if r is None:
        raise not_found("Không tìm thấy thiết bị")
    return r


@router.get("")
def list_devices(
    user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
) -> list[dict[str, Any]]:
    return [_out(conn, d) for d in db.rows(conn.execute(_LIST + " ORDER BY d.id"))]


@router.get("/{did}")
def get_device(
    did: int, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    return _out(conn, _load(conn, did))


def _validate(conn: sqlite3.Connection, body: DeviceIn, exclude: int | None) -> None:
    c = db.row(conn.execute("SELECT type FROM connections WHERE id = ?", (body.connection_id,)))
    if c is None:
        raise invalid("Chọn kết nối", "connection_id")
    tdef = template_def(conn, body.template_id)
    if tdef is None:
        raise invalid("Chọn mẫu thiết bị", "template_id")
    if c["type"] == "rtu" and not 1 <= body.unit_id <= 247:
        raise invalid("Unit ID của Modbus RTU phải từ 1 đến 247", "unit_id")
    dup = conn.execute(
        "SELECT name FROM devices WHERE connection_id = ? AND unit_id = ? AND deleted_at IS NULL AND id != ?",
        (body.connection_id, body.unit_id, exclude or 0),
    ).fetchone()
    if dup:
        raise conflict(
            f"Unit ID {body.unit_id} đã dùng cho {dup['name']} trên kết nối này", "duplicate_unit_id", "unit_id"
        )
    by_key = {c.key: c for c in tdef.channels}
    for ch in body.channels:
        tc = by_key.get(ch.key)
        if tc is not None:
            validate_device_channel(ch, tc, f"channels.{ch.key}")


def _apply_channels(conn: sqlite3.Connection, did: int, body: DeviceIn) -> None:
    tdef = template_def(conn, body.template_id)
    assert tdef is not None
    sync_device_channels(conn, did, tdef)
    by_key = {c.key: c for c in tdef.channels}
    for ch in body.channels:
        if ch.key not in by_key:
            continue
        label = (ch.label or "").strip() or by_key[ch.key].label
        conn.execute(
            "UPDATE channels SET label = ?, display_min = ?, display_max = ?, alarm_low = ?, alarm_high = ?, enabled = ? "
            "WHERE device_id = ? AND key = ?",
            (label, ch.display_min, ch.display_max, ch.alarm_low, ch.alarm_high, int(ch.enabled), did, ch.key),
        )


def _snapshot(conn: sqlite3.Connection, did: int) -> dict[str, Any]:
    d = db.row(
        conn.execute(
            "SELECT name, zone, connection_id, unit_id, template_id, poll_interval_s, enabled FROM devices WHERE id = ?",
            (did,),
        )
    )
    chs = db.rows(
        conn.execute(
            "SELECT key, label, unit, display_min, display_max, alarm_low, alarm_high, enabled FROM channels WHERE device_id = ?",
            (did,),
        )
    )
    return {**(d or {}), "channels": {c["key"]: c for c in chs}}


def _summary(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    out = diff(
        before,
        after,
        {
            "name": "Tên",
            "zone": "Khu vực",
            "unit_id": "Unit ID",
            "poll_interval_s": "Chu kỳ đọc (giây)",
            "enabled": "Đang đọc",
            "connection_id": "Kết nối",
            "template_id": "Mẫu",
        },
    )
    for key, a in after["channels"].items():
        b = before["channels"].get(key)
        if b is None:
            continue
        label, unit = a["label"], a["unit"]
        if a["label"] != b["label"]:
            out.append(f"{b['label']}: nhãn → {a['label']}")
        if (a["display_min"], a["display_max"]) != (b["display_min"], b["display_max"]):
            out.append(
                f"{label}: thang hiển thị {rng(b['display_min'], b['display_max'])} → {rng(a['display_min'], a['display_max'], unit)}"
            )
        if (a["alarm_low"], a["alarm_high"]) != (b["alarm_low"], b["alarm_high"]):
            out.append(
                f"{label}: ngưỡng {rng(b['alarm_low'], b['alarm_high'])} → {rng(a['alarm_low'], a['alarm_high'], unit)}"
            )
        if a["enabled"] != b["enabled"]:
            out.append(f"{label}: {'bật' if a['enabled'] else 'tắt'} kênh")
    return out


@router.post("", status_code=201)
async def create_device(
    body: DeviceIn, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_async_db)
) -> dict[str, Any]:
    _validate(conn, body, None)
    now = now_ms()
    try:
        with db.tx(conn):
            did = conn.execute(
                "INSERT INTO devices(name, zone, connection_id, unit_id, template_id, poll_interval_s, enabled, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    body.name.strip(),
                    body.zone.strip(),
                    body.connection_id,
                    body.unit_id,
                    body.template_id,
                    body.poll_interval_s,
                    int(body.enabled),
                    now,
                    now,
                ),
            ).lastrowid
            assert did is not None
            _apply_channels(conn, did, body)
            db.audit(
                conn,
                user.ref,
                "create",
                "device",
                did,
                None,
                _snapshot(conn, did),
                f"Thêm thiết bị {body.name}, unit ID {body.unit_id}",
            )
    except sqlite3.IntegrityError as e:
        raise conflict(f"Unit ID {body.unit_id} đã dùng trên kết nối này", "duplicate_unit_id", "unit_id") from e
    await collector_client.reload()
    return _out(conn, _load(conn, did))


@router.patch("/{did}")
async def patch_device(
    did: int, body: DeviceIn, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_async_db)
) -> dict[str, Any]:
    _load(conn, did)
    _validate(conn, body, did)
    before = _snapshot(conn, did)
    try:
        with db.tx(conn):
            conn.execute(
                "UPDATE devices SET name = ?, zone = ?, connection_id = ?, unit_id = ?, template_id = ?, poll_interval_s = ?, "
                "enabled = ?, updated_at = ? WHERE id = ?",
                (
                    body.name.strip(),
                    body.zone.strip(),
                    body.connection_id,
                    body.unit_id,
                    body.template_id,
                    body.poll_interval_s,
                    int(body.enabled),
                    now_ms(),
                    did,
                ),
            )
            _apply_channels(conn, did, body)
            after = _snapshot(conn, did)
            changes = _summary(before, after)
            if changes:
                db.audit(conn, user.ref, "update", "device", did, before, after, f"{body.name}: " + "; ".join(changes))
    except sqlite3.IntegrityError as e:
        raise conflict(f"Unit ID {body.unit_id} đã dùng trên kết nối này", "duplicate_unit_id", "unit_id") from e
    await collector_client.reload()
    return _out(conn, _load(conn, did))


@router.delete("/{did}", summary="Xóa mềm: ẩn khỏi danh sách, dữ liệu lịch sử giữ nguyên")
async def delete_device(
    did: int, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_async_db)
) -> dict[str, bool]:
    d = _load(conn, did)
    with db.tx(conn):
        conn.execute("UPDATE devices SET deleted_at = ?, enabled = 0 WHERE id = ?", (now_ms(), did))
        db.audit(
            conn,
            user.ref,
            "delete",
            "device",
            did,
            _snapshot(conn, did),
            None,
            f"Xóa thiết bị {d['name']} (giữ dữ liệu lịch sử)",
        )
    await collector_client.reload()
    return {"ok": True}


class TestReadIn(BaseModel):
    connection_id: int
    unit_id: int
    template_id: int | None = None
    channels: list[ChannelDef] | None = None


@router.post("/test-read", summary="Đọc thử cấu hình chưa lưu qua collector")
async def test_read(
    body: TestReadIn, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_async_db)
) -> dict[str, Any]:
    if conn.execute("SELECT 1 FROM connections WHERE id = ?", (body.connection_id,)).fetchone() is None:
        raise invalid("Chọn kết nối", "connection_id")
    channels = body.channels
    if channels is None:
        tdef = template_def(conn, body.template_id or 0)
        if tdef is None:
            raise invalid("Chọn mẫu thiết bị", "template_id")
        channels = tdef.channels
    payload = {
        "connection_id": body.connection_id,
        "unit_id": body.unit_id,
        "channels": [json.loads(c.model_dump_json()) for c in channels],
    }
    return await collector_client.call("POST", "/test-read", payload, http_timeout=30)

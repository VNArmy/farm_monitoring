"""Kết nối (spec mục 8.2), commissioning (8.5), log frame (8.6). Mọi thao tác chạm bus đi qua collector."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ...core import db
from ...core.errors import conflict, invalid, not_found
from ...core.models import ConnectionIn, RtuParams
from ...core.timeutil import now_ms, zone
from .. import collector_client
from ..auditfmt import diff
from ..auth import User, get_async_db, get_db, require_admin

router = APIRouter(prefix="/api/admin", tags=["Kết nối và commissioning"])

PARAM_LABELS = {
    "port": "Cổng",
    "baudrate": "Baud rate",
    "parity": "Parity",
    "stopbits": "Stop bits",
    "host": "Host",
    "framing": "Kiểu đóng gói",
    "timeout_ms": "Timeout (ms)",
    "retries": "Số lần thử lại",
    "gap_ms": "Nghỉ giữa 2 request (ms)",
}


# --- Cổng serial ---------------------------------------------------------------------------


def list_serial_ports(include_sim: bool = True) -> list[dict[str, Any]]:
    """Ưu tiên /dev/serial/by-id: số ttyUSBx có thể đổi sau khi cắm lại adapter (spec mục 4.1)."""
    info: dict[str, dict[str, Any]] = {}
    try:
        from serial.tools import list_ports

        for p in list_ports.comports():
            info[p.device] = {
                "manufacturer": p.manufacturer,
                "product": p.product or p.description,
                "serial_number": p.serial_number,
            }
    except Exception:
        pass
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    byid = Path("/dev/serial/by-id")
    if byid.is_dir():
        for p in sorted(byid.iterdir()):
            real = os.path.realpath(p)
            out.append({"path": str(p), "device": real, "stable": True, **info.get(real, {})})
            seen.add(real)
    for dev, meta in sorted(info.items()):
        if dev not in seen:
            out.append({"path": dev, "device": dev, "stable": False, **meta})
    if include_sim:
        out.append(
            {
                "path": "sim://demo",
                "device": "sim://demo",
                "stable": True,
                "manufacturer": None,
                "product": "Bus mô phỏng, không cần phần cứng",
                "serial_number": None,
            }
        )
    return out


@router.get("/serial-ports")
def serial_ports(user: User = Depends(require_admin)) -> list[dict[str, Any]]:
    # Bus mô phỏng chỉ hiện khi chạy chế độ dev (GREENHOUSE_SIM=1).
    return list_serial_ports(include_sim=os.environ.get("GREENHOUSE_SIM") == "1")


# --- Kết nối -------------------------------------------------------------------------------


def _load(conn: sqlite3.Connection, cid: int) -> dict[str, Any]:
    r = db.row(conn.execute("SELECT * FROM connections WHERE id = ?", (cid,)))
    if r is None:
        raise not_found("Không tìm thấy kết nối")
    r["params"] = json.loads(r["params"])
    r["enabled"] = bool(r["enabled"])
    return r


def _validate(conn: sqlite3.Connection, body: ConnectionIn, exclude: int | None = None) -> dict[str, Any]:
    try:
        params = body.typed_params()
    except Exception as e:
        errs: list[Any] = getattr(e, "errors", lambda: [])()
        field = "params." + str(errs[0]["loc"][0]) if errs else "params"
        msg = errs[0]["msg"] if errs else str(e)
        raise invalid(f"Tham số không hợp lệ: {msg}", field) from e
    p = params.model_dump()
    if isinstance(params, RtuParams):
        for r in conn.execute(
            "SELECT id, name, params FROM connections WHERE type = 'rtu' AND id != ?", (exclude or 0,)
        ):
            if json.loads(r["params"]).get("port") == params.port:
                raise conflict(
                    f"Cổng này đã dùng cho “{r['name']}”: mỗi bus RS-485 là một cổng serial",
                    "port_in_use",
                    "params.port",
                )
    return p


def _worker_status(status: dict[str, Any] | None, cid: int) -> dict[str, Any] | None:
    if status is None:
        return None
    return next((w for w in status.get("workers", []) if w["connection_id"] == cid), {"state": "stopped"})


@router.get("/connections")
async def list_connections(
    user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_async_db)
) -> list[dict[str, Any]]:
    status = await collector_client.status()
    out = []
    for r in db.rows(conn.execute("SELECT * FROM connections ORDER BY id")):
        r["params"] = json.loads(r["params"])
        r["enabled"] = bool(r["enabled"])
        r["devices"] = db.rows(
            conn.execute(
                "SELECT d.id, d.name, d.unit_id, d.enabled, ds.state, ds.last_rtt_ms, ds.last_ok_ts FROM devices d "
                "LEFT JOIN device_status ds ON ds.device_id = d.id WHERE d.connection_id = ? AND d.deleted_at IS NULL "
                "ORDER BY d.unit_id",
                (r["id"],),
            )
        )
        r["worker"] = _worker_status(status, r["id"])
        out.append(r)
    return out


@router.get("/connections/{cid}")
def get_connection(
    cid: int, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    return _load(conn, cid)


@router.post("/connections", status_code=201)
async def create_connection(
    body: ConnectionIn, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_async_db)
) -> dict[str, Any]:
    params = _validate(conn, body)
    now = now_ms()
    with db.tx(conn):
        cid = conn.execute(
            "INSERT INTO connections(name, type, params, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (body.name.strip(), body.type, json.dumps(params), int(body.enabled), now, now),
        ).lastrowid
        assert cid is not None
        after = {"name": body.name, "type": body.type, "params": params, "enabled": body.enabled}
        db.audit(
            conn, user.ref, "create", "connection", cid, None, after, f"Tạo kết nối {body.name} ({body.type.upper()})"
        )
    await collector_client.reload()
    return _load(conn, cid)


@router.patch("/connections/{cid}")
async def patch_connection(
    cid: int,
    body: dict[str, Any],
    user: User = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_async_db),
) -> dict[str, Any]:
    old = _load(conn, cid)
    merged = ConnectionIn(**{**{k: old[k] for k in ("name", "type", "params", "enabled")}, **body})
    params = _validate(conn, merged, cid)
    changes = diff(old["params"], params, PARAM_LABELS)
    if merged.name != old["name"]:
        changes.insert(0, f"Tên: {old['name']} → {merged.name}")
    if merged.enabled != old["enabled"]:
        changes.append("bật" if merged.enabled else "tắt")
    with db.tx(conn):
        conn.execute(
            "UPDATE connections SET name = ?, type = ?, params = ?, enabled = ?, updated_at = ? WHERE id = ?",
            (merged.name.strip(), merged.type, json.dumps(params), int(merged.enabled), now_ms(), cid),
        )
        if changes:
            after = {"name": merged.name, "type": merged.type, "params": params, "enabled": merged.enabled}
            db.audit(
                conn,
                user.ref,
                "update",
                "connection",
                cid,
                {k: old[k] for k in ("name", "type", "params", "enabled")},
                after,
                f"{merged.name}: " + "; ".join(changes),
            )
    await collector_client.reload()
    return _load(conn, cid)


@router.delete("/connections/{cid}")
async def delete_connection(
    cid: int, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_async_db)
) -> dict[str, bool]:
    old = _load(conn, cid)
    n = conn.execute("SELECT COUNT(*) FROM devices WHERE connection_id = ? AND deleted_at IS NULL", (cid,)).fetchone()[
        0
    ]
    if n:
        raise conflict(f"Còn {n} thiết bị dùng kết nối này", "in_use")
    with db.tx(conn):
        conn.execute("DELETE FROM connections WHERE id = ?", (cid,))
        db.audit(conn, user.ref, "delete", "connection", cid, old, None, f"Xóa kết nối {old['name']}")
    await collector_client.reload()
    return {"ok": True}


class TestIn(BaseModel):
    type: str | None = None
    params: dict[str, Any] | None = None


@router.post("/connections/test", summary="Kiểm tra kết nối chưa lưu")
async def test_new(body: TestIn, user: User = Depends(require_admin)) -> dict[str, Any]:
    if body.type not in ("rtu", "tcp") or body.params is None:
        raise invalid("Thiếu kiểu hoặc tham số kết nối", "type")
    ConnectionIn(name="x", type=body.type, params=body.params).typed_params()  # type: ignore[arg-type]
    return await collector_client.call(
        "POST", "/test-connection", {"type": body.type, "params": body.params}, http_timeout=20
    )


@router.post("/connections/{cid}/test", summary="Kiểm tra kết nối (với tham số đang nhập nếu có)")
async def test_connection(
    cid: int, body: TestIn, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_async_db)
) -> dict[str, Any]:
    old = _load(conn, cid)
    req: dict[str, Any] = {"connection_id": cid}
    if body.params is not None:
        req.update({"type": body.type or old["type"], "params": body.params})
    return await collector_client.call("POST", "/test-connection", req, http_timeout=20)


# --- Commissioning ------------------------------------------------------------------------


class ScanIn(BaseModel):
    from_id: int = Field(1, ge=0, le=255)
    to_id: int = Field(247, ge=0, le=255)
    bauds: list[int] = []
    timeout_ms: int = Field(200, ge=20, le=2000)


@router.post("/connections/{cid}/scan", summary="Quét địa chỉ, trả job id")
async def scan(
    cid: int, body: ScanIn, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_async_db)
) -> dict[str, Any]:
    _load(conn, cid)
    return await collector_client.call("POST", "/scan", {"connection_id": cid, **body.model_dump()})


@router.get("/jobs/{job_id}")
async def job(job_id: int, user: User = Depends(require_admin)) -> dict[str, Any]:
    return await collector_client.call("GET", f"/jobs/{job_id}")


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: int, user: User = Depends(require_admin)) -> dict[str, Any]:
    return await collector_client.call("POST", f"/jobs/{job_id}/cancel")


class SetAddressIn(BaseModel):
    template_id: int
    current_id: int = Field(ge=0, le=255)
    current_baud: int | None = None
    new_id: int = Field(ge=1, le=247)
    new_baud: int | None = None


@router.post("/connections/{cid}/set-address", summary="Đổi địa chỉ hoặc baud rate cảm biến, đọc lại xác nhận")
async def set_address(
    cid: int, body: SetAddressIn, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_async_db)
) -> dict[str, Any]:
    c = _load(conn, cid)
    bus_baud = c["params"].get("baudrate")
    if body.new_baud in (None, bus_baud):
        used = conn.execute(
            "SELECT name FROM devices WHERE connection_id = ? AND unit_id = ? AND deleted_at IS NULL",
            (cid, body.new_id),
        ).fetchone()
        if used:
            raise conflict(f"ID {body.new_id} đang dùng cho {used['name']} trên bus này", "duplicate_unit_id", "new_id")
    result = await collector_client.call(
        "POST", "/set-address", {"connection_id": cid, **body.model_dump()}, http_timeout=30
    )
    with db.tx(conn):
        db.audit(
            conn,
            user.ref,
            "set_address",
            "connection",
            cid,
            {"unit_id": body.current_id, "baud": body.current_baud},
            {"unit_id": body.new_id, "baud": body.new_baud, "ok": result.get("ok")},
            f"{c['name']}: đổi địa chỉ cảm biến ID {body.current_id} → {body.new_id}"
            + (f", baud {body.current_baud} → {body.new_baud}" if body.new_baud != body.current_baud else "")
            + ("" if result.get("ok") else " (chưa xác nhận)"),
        )
    return result


# --- Log frame thô ------------------------------------------------------------------------


class FrameLogIn(BaseModel):
    enabled: bool


@router.get("/connections/{cid}/frame-log")
async def get_frame_log(
    cid: int, limit: int = 80, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_async_db)
) -> dict[str, Any]:
    rows = db.rows(
        conn.execute(
            "SELECT id, ts, dir, hex, note FROM frame_log WHERE connection_id = ? ORDER BY id DESC LIMIT ?",
            (cid, max(1, min(limit, 500))),
        )
    )
    worker = _worker_status(await collector_client.status(), cid)
    until = (worker or {}).get("frame_log_until")
    return {"until": until if until and until > now_ms() else None, "rows": list(reversed(rows))}


@router.post("/connections/{cid}/frame-log", summary="Bật/tắt log frame thô; tự tắt sau 10 phút")
async def set_frame_log(
    cid: int, body: FrameLogIn, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_async_db)
) -> dict[str, Any]:
    _load(conn, cid)
    return await collector_client.call("POST", "/frame-log", {"connection_id": cid, "enabled": body.enabled})


@router.get("/connections/{cid}/frame-log/download")
def download_frame_log(
    cid: int, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
) -> PlainTextResponse:
    tz = zone(db.get_setting(conn, "timezone"))
    lines = []
    for r in conn.execute("SELECT ts, dir, hex, note FROM frame_log WHERE connection_id = ? ORDER BY id", (cid,)):
        t = datetime.fromtimestamp(r["ts"] / 1000, tz).isoformat(timespec="milliseconds")
        lines.append(f"{t}  {r['dir']}  {r['hex'] or '-'}" + (f"  ({r['note']})" if r["note"] else ""))
    return PlainTextResponse(
        "\n".join(lines) + "\n",
        headers={"Content-Disposition": f'attachment; filename="frame-log-ket-noi-{cid}.txt"'},
    )

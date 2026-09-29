"""Mẫu thiết bị (spec mục 4.4, 8.3): thêm, sửa, sao chép, import và export JSON theo định dạng ở mục 4.5."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from ...core import db
from ...core.errors import conflict, not_found
from ...core.models import TemplateDef, validate_template
from ...core.repo import sync_device_channels
from ...core.timeutil import now_ms
from .. import collector_client
from ..auditfmt import diff
from ..auth import User, get_async_db, get_db, require_admin

router = APIRouter(prefix="/api/admin/templates", tags=["Mẫu thiết bị"])

CHANNEL_LABELS = {
    "label": "nhãn",
    "unit": "đơn vị",
    "fc": "FC",
    "address": "địa chỉ",
    "type": "kiểu",
    "byte_order": "thứ tự byte",
    "scale": "hệ số",
    "offset": "offset",
    "min": "hợp lệ từ",
    "max": "hợp lệ đến",
    "display_min": "hiển thị từ",
    "display_max": "hiển thị đến",
    "invalid_value": "mã lỗi",
    "agg": "cách gộp",
    "decimals": "số lẻ",
    "estimate": "ước tính",
}


def _out(conn: sqlite3.Connection, r: dict[str, Any]) -> dict[str, Any]:
    d = json.loads(r["definition"])
    return {
        "id": r["id"],
        "name": r["name"],
        "category": r["category"],
        **d,
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "devices": db.rows(
            conn.execute(
                "SELECT id, name, zone FROM devices WHERE template_id = ? AND deleted_at IS NULL ORDER BY id",
                (r["id"],),
            )
        ),
    }


def _load(conn: sqlite3.Connection, tid: int) -> dict[str, Any]:
    r = db.row(conn.execute("SELECT * FROM device_templates WHERE id = ?", (tid,)))
    if r is None:
        raise not_found("Không tìm thấy mẫu")
    return r


def export_obj(r: dict[str, Any]) -> dict[str, Any]:
    """Định dạng import/export (spec mục 4.5): bỏ trường rỗng cho gọn."""
    t = TemplateDef(name=r["name"], category=r["category"], **json.loads(r["definition"]))
    return t.model_dump(exclude_none=True, exclude_defaults=False)


@router.get("")
def list_templates(
    user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
) -> list[dict[str, Any]]:
    return [_out(conn, r) for r in db.rows(conn.execute("SELECT * FROM device_templates ORDER BY id"))]


@router.get("/{tid}", summary="Chi tiết mẫu; ?download=1 để tải JSON")
def get_template(
    tid: int, download: int = 0, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
) -> Any:
    r = _load(conn, tid)
    if not download:
        return _out(conn, r)
    obj = export_obj(r)
    slug = (
        "".join(ch if ch.isalnum() else "-" for ch in obj["name"].encode("ascii", "ignore").decode()).strip("-").lower()
    )
    return Response(
        json.dumps(obj, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="mau-{slug or "thiet-bi"}.json"'},
    )


def _insert(conn: sqlite3.Connection, t: TemplateDef, user: User, action: str = "create") -> int:
    validate_template(t)
    now = now_ms()
    with db.tx(conn):
        tid = conn.execute(
            "INSERT INTO device_templates(name, category, definition, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (t.name.strip(), t.category, json.dumps(t.definition(), ensure_ascii=False), now, now),
        ).lastrowid
        assert tid is not None
        verb = "Nhập" if action == "import" else "Tạo"
        db.audit(
            conn,
            user.ref,
            action,
            "template",
            tid,
            None,
            t.model_dump(),
            f"{verb} mẫu {t.name}, {len(t.channels)} kênh",
        )
    return tid


@router.post("", status_code=201)
def create_template(
    body: TemplateDef, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    return _out(conn, _load(conn, _insert(conn, body, user)))


@router.post("/import", status_code=201, summary="Nhập mẫu từ JSON (một mẫu hoặc danh sách)")
def import_templates(
    body: dict[str, Any] | list[dict[str, Any]],
    user: User = Depends(require_admin),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    items = body if isinstance(body, list) else [body]
    names = {r[0] for r in conn.execute("SELECT name FROM device_templates")}
    out = []
    for item in items:
        t = TemplateDef(**item)
        if t.name in names:
            t.name = f"{t.name} (nhập)"[:60]
        names.add(t.name)
        out.append(_out(conn, _load(conn, _insert(conn, t, user, "import"))))
    return out


@router.patch("/{tid}")
async def patch_template(
    tid: int, body: TemplateDef, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_async_db)
) -> dict[str, Any]:
    """Sửa mẫu chỉ ảnh hưởng dữ liệu đọc sau đó; nhật ký ghi trước, sau để giải thích khi đồ thị nhảy bậc."""
    old_row = _load(conn, tid)
    old = TemplateDef(name=old_row["name"], category=old_row["category"], **json.loads(old_row["definition"]))
    validate_template(body)
    old_ch = {c.key: c.model_dump() for c in old.channels}
    changes: list[str] = []
    if body.name != old.name:
        changes.append(f"Tên: {old.name} → {body.name}")
    for c in body.channels:
        if c.key not in old_ch:
            changes.append(f"Thêm kênh {c.key}")
        else:
            d = diff(old_ch[c.key], c.model_dump(), CHANNEL_LABELS)
            if d:
                changes.append(f"{c.label}: " + ", ".join(d))
    for key in set(old_ch) - {c.key for c in body.channels}:
        changes.append(f"Bỏ kênh {key}")
    if (old.address_register, old.baud_register) != (body.address_register, body.baud_register):
        changes.append("Đổi thanh ghi cấu hình (FC 06)")
    with db.tx(conn):
        conn.execute(
            "UPDATE device_templates SET name = ?, category = ?, definition = ?, updated_at = ? WHERE id = ?",
            (body.name.strip(), body.category, json.dumps(body.definition(), ensure_ascii=False), now_ms(), tid),
        )
        for (did,) in conn.execute(
            "SELECT id FROM devices WHERE template_id = ? AND deleted_at IS NULL", (tid,)
        ).fetchall():
            sync_device_channels(conn, did, body)
        if changes:
            db.audit(
                conn,
                user.ref,
                "update",
                "template",
                tid,
                old.model_dump(),
                body.model_dump(),
                f"Mẫu {body.name}: " + "; ".join(changes),
            )
    await collector_client.reload()
    return _out(conn, _load(conn, tid))


@router.delete("/{tid}")
def delete_template(
    tid: int, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, bool]:
    r = _load(conn, tid)
    n = conn.execute("SELECT COUNT(*) FROM devices WHERE template_id = ? AND deleted_at IS NULL", (tid,)).fetchone()[0]
    if n:
        raise conflict(f"Còn {n} thiết bị dùng mẫu này", "in_use")
    with db.tx(conn):
        conn.execute("DELETE FROM device_templates WHERE id = ?", (tid,))
        db.audit(conn, user.ref, "delete", "template", tid, export_obj(r), None, f"Xóa mẫu {r['name']}")
    return {"ok": True}

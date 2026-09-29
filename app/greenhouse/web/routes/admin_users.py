"""Người dùng (spec mục 8.1): không xóa cứng; khóa hoặc đổi mật khẩu thu hồi mọi session; không khóa admin cuối cùng."""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...core import db
from ...core.errors import ApiError, not_found
from ...core.timeutil import now_ms
from ..auth import User, check_password_rules, get_db, hash_password, require_admin, temp_password

router = APIRouter(prefix="/api/admin/users", tags=["Người dùng"])

ROLE_NAMES = {"viewer": "Xem", "admin": "Quản trị"}


class UserIn(BaseModel):
    username: str = Field(pattern=r"^[a-z0-9_]{3,32}$")
    role: Literal["viewer", "admin"] = "viewer"
    password: str = Field(max_length=256)


class UserPatch(BaseModel):
    role: Literal["viewer", "admin"] | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(max_length=256)


def _public(u: dict[str, Any], me: User) -> dict[str, Any]:
    return {
        "id": u["id"],
        "username": u["username"],
        "role": u["role"],
        "is_active": bool(u["is_active"]),
        "must_change_password": bool(u["must_change_password"]),
        "created_at": u["created_at"],
        "last_login_at": u["last_login_at"],
        "is_me": u["id"] == me.id,
    }


@router.get("")
def list_users(user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)) -> list[dict[str, Any]]:
    return [_public(u, user) for u in db.rows(conn.execute("SELECT * FROM users ORDER BY id"))]


@router.get("/temp-password", summary="Gợi ý mật khẩu tạm")
def suggest(user: User = Depends(require_admin)) -> dict[str, str]:
    return {"password": temp_password()}


@router.post("", status_code=201)
def create_user(
    body: UserIn, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    check_password_rules(body.password)
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (body.username,)).fetchone():
        raise ApiError(409, "duplicate_username", "Tên đăng nhập đã tồn tại", "username")
    with db.tx(conn):
        uid = conn.execute(
            "INSERT INTO users(username, password_hash, role, is_active, must_change_password, created_at) "
            "VALUES (?, ?, ?, 1, 1, ?)",
            (body.username, hash_password(body.password), body.role, now_ms()),
        ).lastrowid
        db.audit(
            conn,
            user.ref,
            "create",
            "user",
            uid,
            None,
            {"username": body.username, "role": body.role},
            f"Tạo người dùng {body.username}, vai trò {ROLE_NAMES[body.role]}",
        )
    u = db.row(conn.execute("SELECT * FROM users WHERE id = ?", (uid,)))
    assert u is not None
    return _public(u, user)


def _active_admins(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1").fetchone()[0])


@router.patch("/{uid}")
def patch_user(
    uid: int, body: UserPatch, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    u = db.row(conn.execute("SELECT * FROM users WHERE id = ?", (uid,)))
    if u is None:
        raise not_found("Không tìm thấy người dùng")
    role = body.role or u["role"]
    active = u["is_active"] if body.is_active is None else int(body.is_active)
    if u["role"] == "admin" and u["is_active"] and (role != "admin" or not active) and _active_admins(conn) <= 1:
        raise ApiError(409, "last_admin", "Không thể khóa hoặc hạ quyền quản trị viên cuối cùng còn hoạt động.")
    changes = []
    if role != u["role"]:
        changes.append(f"vai trò {ROLE_NAMES[u['role']]} → {ROLE_NAMES[role]}")
    if active != u["is_active"]:
        changes.append("khóa" if not active else "mở khóa")
    with db.tx(conn):
        conn.execute("UPDATE users SET role = ?, is_active = ? WHERE id = ?", (role, active, uid))
        if not active or role != u["role"]:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
        if changes:
            db.audit(
                conn,
                user.ref,
                "update",
                "user",
                uid,
                {"role": u["role"], "is_active": bool(u["is_active"])},
                {"role": role, "is_active": bool(active)},
                f"{u['username']}: {', '.join(changes)}",
            )
    nu = db.row(conn.execute("SELECT * FROM users WHERE id = ?", (uid,)))
    assert nu is not None
    return _public(nu, user)


@router.post("/{uid}/reset-password")
def reset_password(
    uid: int, body: PasswordReset, user: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, bool]:
    u = db.row(conn.execute("SELECT username FROM users WHERE id = ?", (uid,)))
    if u is None:
        raise not_found("Không tìm thấy người dùng")
    check_password_rules(body.password)
    with db.tx(conn):
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
            (hash_password(body.password), uid),
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
        db.audit(conn, user.ref, "reset_password", "user", uid, None, None, f"Đặt lại mật khẩu cho {u['username']}")
    return {"ok": True}

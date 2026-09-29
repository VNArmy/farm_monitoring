"""POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me, POST /api/auth/password."""

from __future__ import annotations

import secrets
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from ...core import db
from ...core.errors import ApiError
from ...core.timeutil import now_ms
from ..auth import (
    DUMMY_HASH,
    FAIL_WINDOW_MS,
    MAX_FAILS,
    SESSION_COOKIE,
    User,
    check_password_rules,
    client_ip,
    create_session,
    current_user,
    get_db,
    hash_password,
    needs_rehash,
    recent_failures,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["Xác thực"])


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class PasswordIn(BaseModel):
    current: str = Field(max_length=256)
    new: str = Field(max_length=256)


def _me(user: User, conn: sqlite3.Connection) -> dict[str, Any]:
    s = db.get_settings(conn)
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "must_change_password": user.must_change_password,
        },
        "csrf_token": user.csrf_token,
        "site_name": s["site_name"],
        "timezone": s["timezone"],
    }


@router.get("/site", summary="Tên site cho trang đăng nhập (công khai)")
def site(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return {"site_name": db.get_setting(conn, "site_name")}


@router.post("/login", summary="Đăng nhập; tối đa 5 lần sai mỗi 10 phút cho mỗi IP")
def login(
    body: LoginIn, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    ip = client_ip(request)
    fails = recent_failures(conn, ip)
    if fails >= MAX_FAILS:
        raise ApiError(429, "too_many_attempts", "Tạm khóa đăng nhập 10 phút vì nhập sai quá nhiều lần.")
    username = body.username.strip().lower()
    u = db.row(conn.execute("SELECT * FROM users WHERE username = ?", (username,)))
    ok = verify_password(body.password, u["password_hash"] if u else DUMMY_HASH)
    if not ok or u is None or not u["is_active"]:
        with db.tx(conn):
            conn.execute("INSERT INTO login_failures(ip, username, ts) VALUES (?, ?, ?)", (ip, username, now_ms()))
        left = MAX_FAILS - fails - 1
        raise ApiError(
            401,
            "invalid_credentials",
            "Sai tên đăng nhập hoặc mật khẩu."
            + (
                f" Còn {left} lần thử trong {FAIL_WINDOW_MS // 60000} phút."
                if left > 0
                else " Đã hết lượt thử, chờ 10 phút."
            ),
        )
    token, csrf = create_session(conn, u["id"], ip)
    with db.tx(conn):
        conn.execute("DELETE FROM login_failures WHERE ip = ?", (ip,))
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_ms(), u["id"]))
        if needs_rehash(u["password_hash"]):
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(body.password), u["id"]))
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=30 * 86400,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    user = User(u["id"], u["username"], u["role"], bool(u["must_change_password"]), csrf, "")
    return _me(user, conn)


@router.post("/logout", summary="Đăng xuất")
def logout(
    response: Response, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, bool]:
    with db.tx(conn):
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (user.token_hash,))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me", summary="Người dùng hiện tại và CSRF token")
def me(user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return _me(user, conn)


@router.post("/password", summary="Đổi mật khẩu của chính mình")
def change_password(
    body: PasswordIn, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)
) -> dict[str, Any]:
    r = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user.id,)).fetchone()
    if r is None or not verify_password(body.current, r["password_hash"]):
        raise ApiError(400, "wrong_password", "Mật khẩu hiện tại không đúng", "current")
    check_password_rules(body.new, "new")
    if secrets.compare_digest(body.new, body.current):
        raise ApiError(400, "same_password", "Mật khẩu mới phải khác mật khẩu hiện tại", "new")
    with db.tx(conn):
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
            (hash_password(body.new), user.id),
        )
        # Đổi mật khẩu thì thu hồi mọi session khác của người đó (spec mục 8.1).
        conn.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user.id, user.token_hash))
        db.audit(conn, user.ref, "password", "user", user.id, None, None, f"{user.username} đổi mật khẩu")
    user.must_change_password = False
    return _me(user, conn)

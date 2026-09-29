"""Đăng nhập (spec mục 8.1, 10): argon2id, session phía server, CSRF, giới hạn lần sai theo IP."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, Request

from ..core import db
from ..core.errors import ApiError
from ..core.timeutil import now_ms

SESSION_COOKIE = "gh_session"
SESSION_IDLE_MS = 7 * 86_400_000  # hết hạn sau 7 ngày không hoạt động
TOUCH_EVERY_MS = 60_000
MAX_FAILS = 5
FAIL_WINDOW_MS = 600_000
MIN_PASSWORD = 10
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

_hasher = PasswordHasher()  # argon2id
_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored: str) -> bool:
    try:
        return _hasher.verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored)
    except InvalidHashError:
        return False


# Băm sẵn để khi tên đăng nhập không tồn tại vẫn tốn thời gian như khi có.
DUMMY_HASH = hash_password(secrets.token_hex(8))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def temp_password() -> str:
    """Mật khẩu tạm dạng rG7m-pQ2x-L9vw: 12 ký tự dễ đọc, không có ký tự dễ nhầm."""
    return "-".join("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(3))


def check_password_rules(password: str, field: str = "password") -> None:
    if len(password) < MIN_PASSWORD:
        raise ApiError(400, "weak_password", f"Mật khẩu tối thiểu {MIN_PASSWORD} ký tự", field)


@dataclass
class User:
    id: int
    username: str
    role: str  # admin | viewer
    must_change_password: bool
    csrf_token: str
    token_hash: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def ref(self) -> tuple[int | None, str | None]:
        return self.id, self.username


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def get_db() -> Iterator[sqlite3.Connection]:
    """Một kết nối riêng cho mỗi request.

    Không dùng kết nối theo thread: FastAPI chạy từng dependency đồng bộ và route trên các thread bất kỳ của thread pool,
    nên kết nối lấy ở thread này sẽ được dùng ở thread khác trong khi thread gốc đã nhận request khác, và hai request
    dùng chung một kết nối SQLite cùng lúc (đọc sai session, lồng giao dịch). Mở kết nối SQLite chỉ tốn vài trăm µs.
    """
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def get_async_db() -> Iterator[sqlite3.Connection]:
    """Cho route async; giống get_db. Trong một request, kết nối chỉ được dùng tuần tự."""
    yield from get_db()


def create_session(conn: sqlite3.Connection, user_id: int, ip: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    now = now_ms()
    with db.tx(conn):
        conn.execute(
            "INSERT INTO sessions(token_hash, user_id, csrf_token, created_at, last_seen_at, expires_at, ip) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token_hash(token), user_id, csrf, now, now, now + SESSION_IDLE_MS, ip),
        )
    return token, csrf


def session_user(request: Request, conn: sqlite3.Connection) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    th = token_hash(token)
    r = conn.execute(
        "SELECT u.id, u.username, u.role, u.must_change_password, s.csrf_token, s.last_seen_at, s.expires_at "
        "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND u.is_active = 1",
        (th,),
    ).fetchone()
    now = now_ms()
    if r is None or r["expires_at"] < now:
        return None
    if now - r["last_seen_at"] > TOUCH_EVERY_MS:
        with db.tx(conn):
            conn.execute(
                "UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE token_hash = ?",
                (now, now + SESSION_IDLE_MS, th),
            )
    return User(r["id"], r["username"], r["role"], bool(r["must_change_password"]), r["csrf_token"], th)


def current_user(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> User:
    """Người dùng đã đăng nhập; request ghi phải kèm X-CSRF-Token khớp với session (spec mục 9)."""
    user = session_user(request, conn)
    if user is None:
        raise ApiError(401, "unauthorized", "Cần đăng nhập")
    if request.method in UNSAFE and not secrets.compare_digest(
        request.headers.get("x-csrf-token", ""), user.csrf_token
    ):
        raise ApiError(403, "csrf", "Thiếu hoặc sai X-CSRF-Token")
    return user


def require_viewer(user: User = Depends(current_user)) -> User:
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise ApiError(403, "forbidden", "Chỉ quản trị viên được thao tác này")
    if user.must_change_password:
        raise ApiError(403, "password_change_required", "Đổi mật khẩu tạm trước khi cấu hình")
    return user


def recent_failures(conn: sqlite3.Connection, ip: str) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM login_failures WHERE ip = ? AND ts > ?", (ip, now_ms() - FAIL_WINDOW_MS)
        ).fetchone()[0]
    )

"""SQLite chế độ WAL: kết nối, giao dịch, migration đánh số, cài đặt dạng key/value, nhật ký thay đổi."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import config
from .timeutil import now_ms

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

DEFAULT_SETTINGS: dict[str, Any] = {
    "site_name": "Nhà kính",
    "timezone": "Asia/Ho_Chi_Minh",
    "public_url": "",
    "site_lat": None,
    "site_lng": None,
    "raw_retention_days": 365,
    "backup_time": "02:00",
    "backup_keep": 7,
    "hmi_layout": "cards",
    "hmi_cards": None,
    "hmi_allow_charts": True,
    "hmi_reload_token": "",
    "agg_watermark": None,
}


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else config.db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=5, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_local = threading.local()


def thread_conn() -> sqlite3.Connection:
    """Một kết nối cho mỗi thread; thread pool của web dùng lại thread nên dùng lại kết nối."""
    path = str(config.db_path())
    conn = getattr(_local, "conn", None)
    if conn is None or getattr(_local, "path", None) != path:
        conn = connect(path)
        _local.conn = conn
        _local.path = path
    return conn


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Giao dịch ghi; BEGIN IMMEDIATE lấy khóa ghi ngay để tránh deadlock khi nâng cấp khóa."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# --- Migration -------------------------------------------------------------------------------


def migrations() -> list[tuple[int, Path]]:
    out = []
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        m = re.match(r"^(\d+)_", p.name)
        if m:
            out.append((int(m.group(1)), p))
    return out


def schema_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)"
    )
    r = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(r[0] or 0)


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Chạy các migration chưa áp dụng theo thứ tự số. Chạy lặp lại không lỗi."""
    current = schema_version(conn)
    applied = []
    for version, path in migrations():
        if version <= current:
            continue
        sql = path.read_text(encoding="utf-8")
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stmt in _split_sql(sql):
                conn.execute(stmt)
            conn.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)", (version, now_ms()))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        applied.append(version)
    with tx(conn):
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, json.dumps(value)))
    return applied


def _split_sql(sql: str) -> list[str]:
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


# --- Cài đặt -------------------------------------------------------------------------------


def get_setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    r = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if r is None:
        return DEFAULT_SETTINGS.get(key, default)
    return json.loads(r["value"])


def get_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    for r in conn.execute("SELECT key, value FROM settings"):
        out[r["key"]] = json.loads(r["value"])
    return out


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )


# --- Nhật ký thay đổi --------------------------------------------------------------------


def audit(
    conn: sqlite3.Connection,
    user: tuple[int | None, str | None],
    action: str,
    entity: str,
    entity_id: int | None,
    before: Any,
    after: Any,
    summary: str,
) -> None:
    conn.execute(
        "INSERT INTO audit_log(ts, user_id, username, action, entity, entity_id, before, after, summary) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            now_ms(),
            user[0],
            user[1],
            action,
            entity,
            entity_id,
            None if before is None else json.dumps(before, ensure_ascii=False),
            None if after is None else json.dumps(after, ensure_ascii=False),
            summary,
        ),
    )


def rows(cur: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]


def row(cur: sqlite3.Cursor) -> dict[str, Any] | None:
    r = cur.fetchone()
    return dict(r) if r is not None else None

"""Gộp 5 phút (tự bù cửa sổ thiếu), xóa dữ liệu thô quá hạn, backup bằng VACUUM INTO, kiểm tra đồng bộ giờ."""

from __future__ import annotations

import logging
import math
import os
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core import config, db
from ..core.repo import template_defs
from ..core.timeutil import now_ms, zone

log = logging.getLogger("greenhouse.maintenance")

BUCKET_MS = 300_000
# Chờ thêm sau khi cửa sổ kết thúc: bản ghi được commit theo lô 5 giây.
LATE_MS = 15_000
DAY_MS = 86_400_000


def _channel_aggs(conn: sqlite3.Connection) -> dict[int, str]:
    tdefs = template_defs(conn)
    out = {}
    for r in conn.execute("SELECT ch.id, ch.key, d.template_id FROM channels ch JOIN devices d ON d.id = ch.device_id"):
        tdef = tdefs.get(r["template_id"])
        agg = "mean"
        if tdef is not None:
            agg = next((c.agg for c in tdef.channels if c.key == r["key"]), "mean")
        out[r["id"]] = agg
    return out


def aggregate(conn: sqlite3.Connection, now: int | None = None) -> int:
    """Gộp các cửa sổ 5 phút đã kết thúc vào readings_5m. Trả về số cửa sổ đã ghi."""
    now = now_ms() if now is None else now
    upto = (now - LATE_MS) // BUCKET_MS * BUCKET_MS
    wm = db.get_setting(conn, "agg_watermark")
    if wm is None:
        first = conn.execute("SELECT MIN(ts) FROM readings").fetchone()[0]
        if first is None:
            with db.tx(conn):
                db.set_setting(conn, "agg_watermark", upto)
            return 0
        wm = int(first) // BUCKET_MS * BUCKET_MS
    wm = int(wm)
    aggs = _channel_aggs(conn)
    written = 0
    while wm < upto:
        end = min(upto, wm + DAY_MS)
        with db.tx(conn):
            for cid, agg in aggs.items():
                if agg == "circular_mean":
                    written += _aggregate_circular(conn, cid, wm, end)
                    continue
                cur = conn.execute(
                    "INSERT OR REPLACE INTO readings_5m(channel_id, ts, avg, min, max, count) "
                    "SELECT channel_id, (ts / 300000) * 300000, AVG(value), MIN(value), MAX(value), COUNT(*) "
                    "FROM readings WHERE channel_id = ? AND ts >= ? AND ts < ? AND quality = 0 GROUP BY ts / 300000",
                    (cid, wm, end),
                )
                written += max(0, cur.rowcount)
            db.set_setting(conn, "agg_watermark", end)
        wm = end
    return written


def _aggregate_circular(conn: sqlite3.Connection, cid: int, start: int, end: int) -> int:
    """Trung bình góc: 350° và 10° ra 0°. Lưu sin_avg, cos_avg để gộp tiếp chính xác."""
    buckets: dict[int, list[float]] = {}
    for ts, value in conn.execute(
        "SELECT ts, value FROM readings WHERE channel_id = ? AND ts >= ? AND ts < ? AND quality = 0", (cid, start, end)
    ):
        buckets.setdefault(ts // BUCKET_MS * BUCKET_MS, []).append(value)
    for b, vals in buckets.items():
        s = sum(math.sin(math.radians(v)) for v in vals) / len(vals)
        c = sum(math.cos(math.radians(v)) for v in vals) / len(vals)
        conn.execute(
            "INSERT OR REPLACE INTO readings_5m(channel_id, ts, avg, min, max, count, sin_avg, cos_avg) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, b, math.degrees(math.atan2(s, c)) % 360, min(vals), max(vals), len(vals), s, c),
        )
    return len(buckets)


def prune(conn: sqlite3.Connection, now: int | None = None) -> None:
    now = now_ms() if now is None else now
    days = int(db.get_setting(conn, "raw_retention_days", 365))
    cutoff = now - days * DAY_MS
    wm = db.get_setting(conn, "agg_watermark")
    if wm is not None:
        cutoff = min(cutoff, int(wm))  # không xóa dữ liệu thô chưa gộp
    for (cid,) in conn.execute("SELECT id FROM channels").fetchall():
        with db.tx(conn):
            conn.execute("DELETE FROM readings WHERE channel_id = ? AND ts < ?", (cid, cutoff))
    with db.tx(conn):
        conn.execute("DELETE FROM device_stats_5m WHERE ts < ?", (now - 8 * DAY_MS,))
        conn.execute("DELETE FROM frame_log WHERE ts < ?", (now - DAY_MS,))
        conn.execute("DELETE FROM frame_log WHERE id < (SELECT MAX(id) - 20000 FROM frame_log)")
        conn.execute("DELETE FROM device_events WHERE ts < ?", (now - 365 * DAY_MS,))
        conn.execute("DELETE FROM login_failures WHERE ts < ?", (now - DAY_MS,))
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))


def run_backup(path: Path | None = None, now: int | None = None) -> dict[str, Any]:
    """Backup bằng VACUUM INTO sang thư mục backup (nên đặt ở ổ khác hoặc USB), giữ N bản gần nhất.

    Dùng kết nối riêng: VACUUM INTO chỉ đọc nên không chặn ghi nhờ WAL.
    """
    now = now_ms() if now is None else now
    conn = db.connect(path)
    try:
        tz = db.get_setting(conn, "timezone")
        stamp = datetime.fromtimestamp(now / 1000, zone(tz)).strftime("%Y%m%d-%H%M%S")
        bdir = config.backup_dir()
        bdir.mkdir(parents=True, exist_ok=True)
        target = bdir / f"greenhouse-{stamp}.db"
        tmp = bdir / (target.name + ".tmp")
        if tmp.exists():
            tmp.unlink()
        conn.execute("VACUUM INTO ?", (str(tmp),))
        os.replace(tmp, target)
        keep = max(1, int(db.get_setting(conn, "backup_keep", 7)))
        for old in sorted(bdir.glob("greenhouse-*.db"), key=lambda p: p.name, reverse=True)[keep:]:
            try:
                old.unlink()
            except OSError:
                pass
        info = {"ts": now, "file": target.name, "size": target.stat().st_size}
        with db.tx(conn):
            db.set_setting(conn, "last_backup", info)
        log.info("Đã backup %s (%d byte)", target.name, info["size"])
        return info
    finally:
        conn.close()


def backup_due(conn: sqlite3.Connection, now: int | None = None) -> bool:
    now = now_ms() if now is None else now
    tz = zone(db.get_setting(conn, "timezone"))
    local = datetime.fromtimestamp(now / 1000, tz)
    try:
        hh, mm = (int(x) for x in str(db.get_setting(conn, "backup_time", "02:00")).split(":"))
    except ValueError:
        hh, mm = 2, 0
    target = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    last = db.get_setting(conn, "last_backup") or {}
    return local >= target and float(last.get("ts", 0)) < target.timestamp() * 1000


def latest_backup() -> Path | None:
    files = sorted(config.backup_dir().glob("greenhouse-*.db"), key=lambda p: p.name, reverse=True)
    return files[0] if files else None


def clock_synced() -> bool | None:
    """True/False theo NTP (chrony qua timedatectl); None khi không kiểm tra được (máy không phải Linux)."""
    try:
        out = subprocess.run(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"], capture_output=True, text=True, timeout=2
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() == "yes"

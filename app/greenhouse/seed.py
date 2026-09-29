"""Nạp cấu hình seed (seed/templates.json theo spec mục 4.5, seed/devices.json) và dữ liệu mẫu cho chế độ demo."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .collector import maintenance
from .core import config, db
from .core.models import ConnectionIn, TemplateDef, validate_template
from .core.repo import sync_device_channels
from .core.timeutil import now_ms, zone
from .sim.nodes import ADDR_REGISTER, BAUD_CODES, BAUD_REGISTER, physics

SIM_PORT = "sim://demo"
SYSTEM_USER = (None, "hệ thống")

# Chỉ dùng cho demo; hệ thống thật do quản trị viên đặt ngưỡng.
DEMO_CHANNELS = {
    ("Node 02 · Nhiệt ẩm, ánh sáng", "temperature"): {
        "display_min": 10,
        "display_max": 40,
        "alarm_low": 18,
        "alarm_high": 32,
    },
    ("Node 02 · Nhiệt ẩm, ánh sáng", "humidity"): {"alarm_low": 60, "alarm_high": 90},
    ("Node 01 · Tốc độ gió", "wind_speed"): {"alarm_high": 10},
}


def load_json(name: str) -> Any:
    return json.loads((config.seed_dir() / name).read_text(encoding="utf-8"))


def insert_template(conn: sqlite3.Connection, t: TemplateDef) -> int:
    validate_template(t)
    now = now_ms()
    cur = conn.execute(
        "INSERT INTO device_templates(name, category, definition, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (t.name, t.category, json.dumps(t.definition(), ensure_ascii=False), now, now),
    )
    return int(cur.lastrowid or 0)


def seed(conn: sqlite3.Connection, serial_port: str, demo: bool = False) -> bool:
    """Tạo kết nối, mẫu và thiết bị từ file seed. Bỏ qua (trả False) nếu CSDL đã có kết nối."""
    if conn.execute("SELECT COUNT(*) FROM connections").fetchone()[0]:
        return False
    templates = [TemplateDef(**t) for t in load_json("templates.json")]
    cfg = json.loads(json.dumps(load_json("devices.json")).replace("${SERIAL_PORT}", serial_port))
    now = now_ms()
    with db.tx(conn):
        tids = {}
        for t in templates:
            if demo and t.name.startswith("Node CO2"):
                # Node mô phỏng có thanh ghi địa chỉ và baud rate để thử công cụ đổi địa chỉ (spec mục 8.5).
                t.address_register, t.baud_register = ADDR_REGISTER, BAUD_REGISTER
                t.baud_codes = {str(k): v for k, v in BAUD_CODES.items() if k <= 19200}
            tids[t.name] = insert_template(conn, t)
        cids = {}
        for c in cfg["connections"]:
            ci = ConnectionIn(name=c["name"], type=c["type"], params=c["params"])
            params = ci.typed_params().model_dump()
            cur = conn.execute(
                "INSERT INTO connections(name, type, params, enabled, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
                (ci.name, ci.type, json.dumps(params), now, now),
            )
            cids[ci.name] = cur.lastrowid
        tdefs = {t.name: t for t in templates}
        for d in cfg["devices"]:
            cur = conn.execute(
                "INSERT INTO devices(name, zone, connection_id, unit_id, template_id, poll_interval_s, enabled, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    d["name"],
                    d.get("zone", ""),
                    cids[d["connection"]],
                    d["unit_id"],
                    tids[d["template"]],
                    d.get("poll_interval_s", 10),
                    now,
                    now,
                ),
            )
            sync_device_channels(conn, int(cur.lastrowid or 0), tdefs[d["template"]])
        if demo:
            for (dev, key), values in DEMO_CHANNELS.items():
                sets = ", ".join(f"{k} = ?" for k in values)
                conn.execute(
                    f"UPDATE channels SET {sets} WHERE key = ? AND device_id = (SELECT id FROM devices WHERE name = ?)",
                    (*values.values(), key, dev),
                )
            db.set_setting(conn, "site_name", "Nhà kính demo")
        db.audit(
            conn,
            SYSTEM_USER,
            "create",
            "seed",
            None,
            None,
            {"connections": list(cids), "templates": list(tids), "devices": [d["name"] for d in cfg["devices"]]},
            f"Cấu hình ban đầu: {len(cids)} kết nối, {len(tids)} mẫu, {len(cfg['devices'])} thiết bị",
        )
    return True


def backfill_demo(conn: sqlite3.Connection, days: int = 7, now: int | None = None) -> int:
    """Dữ liệu thô 10 giây/lần cho các ngày trước; có một lần Node 02 mất kết nối 02:10–05:40."""
    now = now_ms() if now is None else now
    tz = zone(db.get_setting(conn, "timezone"))
    chans = conn.execute(
        "SELECT ch.id, ch.key, ch.alarm_low, ch.alarm_high, d.name, d.id AS device_id FROM channels ch "
        "JOIN devices d ON d.id = ch.device_id WHERE d.deleted_at IS NULL"
    ).fetchall()
    if not chans:
        return 0
    local_now = datetime.fromtimestamp(now / 1000, tz)
    gap_day = (local_now - timedelta(days=min(3, days - 1))).replace(hour=2, minute=10, second=0, microsecond=0)
    gap = (gap_day.timestamp() * 1000, gap_day.replace(hour=5, minute=40).timestamp() * 1000)
    start = (now - days * 86_400_000) // 10_000 * 10_000
    end = now - 30_000
    rows: list[tuple[int, int, float, int]] = []
    for ts in range(start, end, 10_000):
        v = physics(ts / 1000)
        for ch in chans:
            if ch["name"].startswith("Node 02") and gap[0] <= ts < gap[1]:
                continue
            rows.append((ch["id"], ts + ch["device_id"] * 97, v[ch["key"]], 0))
    last = physics(end / 1000)
    with db.tx(conn):
        conn.executemany("INSERT OR REPLACE INTO readings(channel_id, ts, value, quality) VALUES (?, ?, ?, ?)", rows)
        for ch in chans:
            value = last[ch["key"]]
            alarm = None
            if ch["alarm_high"] is not None and value > ch["alarm_high"]:
                alarm = "high"
            elif ch["alarm_low"] is not None and value < ch["alarm_low"]:
                alarm = "low"
            conn.execute(
                "INSERT OR REPLACE INTO channel_latest(channel_id, ts, value, quality, alarm, alarm_since) "
                "VALUES (?, ?, ?, 'good', ?, ?)",
                (ch["id"], end, value, alarm, end if alarm else None),
            )
        for did in {ch["device_id"] for ch in chans}:
            conn.execute(
                "INSERT OR REPLACE INTO device_status(device_id, state, since, last_ok_ts, consecutive_failures, "
                "last_rtt_ms, counters, updated_at) VALUES (?, 'online', ?, ?, 0, ?, '{}', ?)",
                (did, start, end, 30 + did * 7, end),
            )
            for b in range((now - 86_400_000) // 300_000 * 300_000, now // 300_000 * 300_000, 300_000):
                timeouts = 1 if (b // 300_000 + did * 7) % 97 == 0 else 0
                conn.execute(
                    "INSERT OR REPLACE INTO device_stats_5m(device_id, ts, requests, ok, timeout, rtt_sum, rtt_n) "
                    "VALUES (?, ?, 30, ?, ?, ?, ?)",
                    (did, b, 30 - timeouts, timeouts, (30 - timeouts) * (32 + did * 7), 30 - timeouts),
                )
        db.set_setting(conn, "agg_watermark", None)
    maintenance.aggregate(conn, now)
    return len(rows)


def seed_file_path() -> Path:
    return config.seed_dir()

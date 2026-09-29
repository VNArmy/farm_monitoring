"""Gộp 5 phút (khớp với dữ liệu thô khi so bằng SQL, bù cửa sổ thiếu, trung bình góc), truy vấn biểu đồ,
backup bằng VACUUM INTO giữ N bản, xóa dữ liệu thô quá hạn."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from greenhouse.collector import maintenance
from greenhouse.core import config, db
from greenhouse.core.models import TemplateDef
from greenhouse.core.repo import sync_device_channels
from greenhouse.core.timeutil import zone
from greenhouse.seed import insert_template, seed
from greenhouse.web.services.readings import export_csv, history

BUCKET = 300_000
DAY = 86_400_000
T0 = 1_780_002_000_000  # mốc tròn giờ (giờ Việt Nam lệch UTC số giờ nguyên)
TZ = "Asia/Ho_Chi_Minh"


def channel_id(conn: sqlite3.Connection, key: str) -> int:
    return int(conn.execute("SELECT id FROM channels WHERE key = ?", (key,)).fetchone()[0])


@pytest.fixture
def seeded(conn: sqlite3.Connection) -> sqlite3.Connection:
    seed(conn, "sim://maint")
    return conn


def insert(conn: sqlite3.Connection, cid: int, rows: list[tuple[int, float, int]]) -> None:
    with db.tx(conn):
        conn.executemany(
            "INSERT INTO readings(channel_id, ts, value, quality) VALUES (?, ?, ?, ?)",
            [(cid, ts, v, q) for ts, v, q in rows],
        )


def test_aggregate_matches_raw_sql(seeded: sqlite3.Connection) -> None:
    conn = seeded
    cid = channel_id(conn, "temperature")
    rows = [(T0 + i * 10_000 + (i % 3) * 7, 20 + (i % 17) * 0.37, 0) for i in range(6 * 60)]  # 1 giờ, 10 giây/lần
    rows += [(T0 + 123_456, 999.0, 1)]  # ngoài phạm vi: không được gộp
    insert(conn, cid, rows)
    n = maintenance.aggregate(conn, now=T0 + 2 * 3_600_000)
    assert n == 12
    agg = conn.execute(
        "SELECT ts, avg, min, max, count FROM readings_5m WHERE channel_id = ? ORDER BY ts", (cid,)
    ).fetchall()
    raw = conn.execute(
        "SELECT ts / 300000 * 300000, AVG(value), MIN(value), MAX(value), COUNT(*) FROM readings "
        "WHERE channel_id = ? AND quality = 0 GROUP BY ts / 300000 ORDER BY 1",
        (cid,),
    ).fetchall()
    assert [tuple(r) for r in agg] == pytest.approx([tuple(r) for r in raw])
    assert all(r[4] == 30 for r in agg)
    assert db.get_setting(conn, "agg_watermark") == (T0 + 2 * 3_600_000 - maintenance.LATE_MS) // BUCKET * BUCKET


def test_aggregate_waits_for_late_batches_and_fills_missing_windows(seeded: sqlite3.Connection) -> None:
    conn = seeded
    cid = channel_id(conn, "humidity")
    insert(conn, cid, [(T0 + i * 10_000, 70.0, 0) for i in range(60)])  # 10 phút
    # Cửa sổ vừa kết thúc chưa gộp (chờ lô 5 giây commit xong)
    maintenance.aggregate(conn, now=T0 + BUCKET + 5_000)
    assert conn.execute("SELECT COUNT(*) FROM readings_5m").fetchone()[0] == 0
    maintenance.aggregate(conn, now=T0 + BUCKET + maintenance.LATE_MS)
    assert conn.execute("SELECT COUNT(*) FROM readings_5m").fetchone()[0] == 1
    # Collector dừng 3 ngày rồi chạy lại: các cửa sổ thiếu được bù
    insert(conn, cid, [(T0 + 3 * DAY + i * 10_000, 72.0, 0) for i in range(30)])
    maintenance.aggregate(conn, now=T0 + 3 * DAY + 3_600_000)
    ts = [r[0] for r in conn.execute("SELECT ts FROM readings_5m ORDER BY ts")]
    assert ts == [T0, T0 + BUCKET, T0 + 3 * DAY]


def test_circular_mean_for_direction(conn: sqlite3.Connection) -> None:
    seed(conn, "sim://dir")
    t = TemplateDef(
        name="Hướng gió",
        category="wind",
        channels=[
            {"key": "wind_dir", "label": "Hướng gió", "unit": "°", "fc": 4, "address": 0, "type": "uint16"},  # type: ignore[list-item]
        ],
    )
    t.channels[0].agg = "circular_mean"
    with db.tx(conn):
        tid = insert_template(conn, t)
        did = conn.execute(
            "INSERT INTO devices(name, connection_id, unit_id, template_id, created_at, updated_at) "
            "VALUES ('Hướng gió', 1, 9, ?, 0, 0)",
            (tid,),
        ).lastrowid
        assert did is not None
        sync_device_channels(conn, did, t)
    cid = channel_id(conn, "wind_dir")
    insert(
        conn, cid, [(T0, 350.0, 0), (T0 + 10_000, 10.0, 0), (T0 + BUCKET, 90.0, 0), (T0 + BUCKET + 10_000, 180.0, 0)]
    )
    maintenance.aggregate(conn, now=T0 + 3_600_000)
    avgs = [r[0] for r in conn.execute("SELECT avg FROM readings_5m WHERE channel_id = ? ORDER BY ts", (cid,))]
    assert min(avgs[0], 360 - avgs[0]) == pytest.approx(0, abs=1e-9)  # 350° và 10° ra 0°, không phải 180°
    assert avgs[1] == pytest.approx(135)
    # Gộp tiếp theo giờ từ readings_5m vẫn là trung bình góc
    res = history(conn, [cid], T0 - 30 * DAY, T0 + 3_600_000, 100, TZ, T0 + 3_600_000)
    [series] = res["series"]
    assert res["bucket_ms"] >= BUCKET
    assert len(series["points"]) == 1


def test_history_uses_aggregates_plus_raw_tail(seeded: sqlite3.Connection) -> None:
    conn = seeded
    cid = channel_id(conn, "temperature")
    rows = [(T0 + i * 10_000, 20 + (i % 97) * 0.1, 0) for i in range(3 * 8640)]  # 3 ngày
    insert(conn, cid, rows)
    end = T0 + 3 * DAY
    maintenance.aggregate(conn, now=T0 + DAY + 12 * 3_600_000)  # gộp được một nửa, phần sau đọc từ thô
    res = history(conn, [cid], T0, end, 100, TZ, end)
    assert res["bucket_ms"] == 3_600_000
    [s] = res["series"]
    assert len(s["points"]) == 72
    raw = {
        r[0]: tuple(r[1:])
        for r in conn.execute(
            "SELECT ts / 3600000 * 3600000, AVG(value), MIN(value), MAX(value) FROM readings "
            "WHERE channel_id = ? GROUP BY ts / 3600000",
            (cid,),
        )
    }
    for t, avg, lo, hi in s["points"]:
        assert (avg, lo, hi) == pytest.approx(raw[t], abs=1e-3)
    assert s["gaps"] == []
    assert s["stats"]["min"] == 20.0


def test_history_raw_and_gaps(seeded: sqlite3.Connection) -> None:
    conn = seeded
    cid = channel_id(conn, "humidity")
    rows = [(T0 + i * 10_000, 70.0, 0) for i in range(180) if not 60 <= i < 120]  # mất 10 phút ở giữa
    insert(conn, cid, rows)
    res = history(conn, [cid], T0, T0 + 1_800_000, 2000, TZ, T0 + 1_800_000)
    [s] = res["series"]
    assert res["bucket_ms"] == 0
    assert len(s["points"]) == 120
    assert s["gaps"] == [[T0 + 59 * 10_000 + 10_000, T0 + 120 * 10_000]]


def test_export_csv_raw_and_wide(seeded: sqlite3.Connection) -> None:
    conn = seeded
    t, h = channel_id(conn, "temperature"), channel_id(conn, "humidity")
    insert(conn, t, [(T0 + i * 10_000, 25.5, 0) for i in range(720)])
    insert(conn, h, [(T0 + i * 10_000, 80.0, 0) for i in range(720)] + [(T0 + 5, 130.0, 1)])
    raw = "".join(export_csv(conn, [t, h], T0, T0 + 60_000, "raw", TZ))
    assert raw.startswith("﻿timestamp,kênh,giá trị,chất lượng\r\n")
    assert "out_of_range" in raw
    first = raw.splitlines()[1]
    assert first.startswith(datetime.fromtimestamp(T0 / 1000, zone(TZ)).isoformat(timespec="milliseconds"))
    assert "+07:00" in first
    wide = "".join(export_csv(conn, [t, h], T0, T0 + 2 * 3_600_000, "1h", TZ)).splitlines()
    assert wide[0] == "﻿timestamp,Nhiệt độ · Khu A (°C),Độ ẩm · Khu A (%RH)"
    assert len(wide) == 1 + 2 + (1 if T0 % 3_600_000 else 0)
    assert wide[1].endswith(",25.5,80.0")


# --- Backup, xóa dữ liệu cũ --------------------------------------------------------------------


def test_backup_keeps_n_latest_and_is_consistent(seeded: sqlite3.Connection, isolated: Path) -> None:
    conn = seeded
    with db.tx(conn):
        db.set_setting(conn, "backup_keep", 3)
    for day in range(5):
        info = maintenance.run_backup(config.db_path(), now=T0 + day * DAY)
    files = sorted(p.name for p in (isolated / "backups").glob("*.db"))
    assert len(files) == 3
    assert files[-1] == info["file"]
    assert db.get_setting(conn, "last_backup")["file"] == info["file"]
    b = sqlite3.connect(isolated / "backups" / info["file"])
    try:
        assert b.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert b.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 3
    finally:
        b.close()


def test_backup_due_at_configured_local_time(seeded: sqlite3.Connection) -> None:
    conn = seeded
    tz = zone(TZ)
    at = lambda h, m=0: int(datetime(2026, 9, 29, h, m, tzinfo=tz).timestamp() * 1000)  # noqa: E731
    assert maintenance.backup_due(conn, now=at(1, 59)) is False
    assert maintenance.backup_due(conn, now=at(2, 0)) is True
    with db.tx(conn):
        db.set_setting(conn, "last_backup", {"ts": at(2, 1), "file": "x", "size": 1})
    assert maintenance.backup_due(conn, now=at(23, 0)) is False


def test_prune_keeps_unaggregated_raw(seeded: sqlite3.Connection) -> None:
    conn = seeded
    cid = channel_id(conn, "temperature")
    with db.tx(conn):
        db.set_setting(conn, "raw_retention_days", 30)
    old, recent = T0 - 40 * DAY, T0 - DAY
    insert(conn, cid, [(old, 1.0, 0), (recent, 2.0, 0)])
    with db.tx(conn):
        db.set_setting(conn, "agg_watermark", old - BUCKET)  # chưa gộp: không được xóa
    maintenance.prune(conn, now=T0)
    assert conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 2
    maintenance.aggregate(conn, now=T0)
    maintenance.prune(conn, now=T0)
    assert [r[0] for r in conn.execute("SELECT value FROM readings")] == [2.0]
    assert conn.execute("SELECT COUNT(*) FROM readings_5m").fetchone()[0] == 2  # dữ liệu gộp giữ nguyên

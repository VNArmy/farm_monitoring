"""Ghi lô: gom bản ghi trong bộ nhớ, commit mỗi 5 giây hoặc khi đủ 500 bản ghi (spec mục 5).

Mỗi commit là một transaction: thêm vào readings, cập nhật channel_latest, device_status, sự kiện, bộ đếm, log frame.
Mọi thao tác CSDL chạy trên một thread riêng với một kết nối riêng, để không chặn vòng lặp asyncio.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core import db
from ..core.timeutil import now_ms

log = logging.getLogger("greenhouse.collector")

FLUSH_INTERVAL_S = 5.0
FLUSH_MAX_READINGS = 500
STATS_BUCKET_MS = 300_000
STAT_KEYS = ("requests", "ok", "timeout", "crc", "exception", "sensor", "io", "rtt_sum", "rtt_n")


@dataclass
class Batch:
    readings: list[tuple[int, int, float, int]] = field(default_factory=list)
    latest: dict[int, dict[str, Any]] = field(default_factory=dict)
    status: dict[int, dict[str, Any]] = field(default_factory=dict)
    events: list[tuple[int, int, str, str | None]] = field(default_factory=list)
    stats: dict[tuple[int, int], dict[str, float]] = field(default_factory=dict)
    frames: list[tuple[int, int, str, str, str | None]] = field(default_factory=list)

    def empty(self) -> bool:
        return not (self.readings or self.latest or self.status or self.events or self.stats or self.frames)


class DbExecutor:
    """Một thread, một kết nối SQLite."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="db")
        self._conn: sqlite3.Connection | None = None

    def _get(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = db.connect(self.path)
        return self._conn

    async def run(self, fn: Any, *args: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.pool, lambda: fn(self._get(), *args))

    def shutdown(self) -> None:
        def close() -> None:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

        self.pool.submit(close).result()
        self.pool.shutdown(wait=True)


class Writer:
    def __init__(self, dbx: DbExecutor):
        self.dbx = dbx
        self.batch = Batch()
        self.last_commit_ms: int | None = None
        self.commits = 0
        self._kick = asyncio.Event()
        self._lock = asyncio.Lock()

    # --- ghi vào lô ---------------------------------------------------------------------------

    def reading(self, channel_id: int, ts: int, value: float, quality: int) -> None:
        self.batch.readings.append((channel_id, ts, value, quality))
        if len(self.batch.readings) >= FLUSH_MAX_READINGS:
            self._kick.set()

    def latest(self, channel_id: int, **row: Any) -> None:
        self.batch.latest[channel_id] = row

    def status(self, device_id: int, **row: Any) -> None:
        self.batch.status[device_id] = row

    def event(self, device_id: int, ts: int, type_: str, detail: str | None = None) -> None:
        self.batch.events.append((device_id, ts, type_, detail))

    def stats(self, device_id: int, ts: int, **inc: float) -> None:
        key = (device_id, ts // STATS_BUCKET_MS * STATS_BUCKET_MS)
        cur = self.batch.stats.setdefault(key, dict.fromkeys(STAT_KEYS, 0.0))
        for k, v in inc.items():
            cur[k] += v

    def frame(self, connection_id: int, ts: int, direction: str, hexstr: str, note: str | None) -> None:
        self.batch.frames.append((connection_id, ts, direction, hexstr, note))

    # --- commit ------------------------------------------------------------------------------

    async def run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._kick.wait(), FLUSH_INTERVAL_S)
            except TimeoutError:
                pass
            self._kick.clear()
            try:
                await self.flush()
            except Exception:
                log.exception("Không ghi được lô dữ liệu")

    async def flush(self) -> None:
        async with self._lock:
            batch, self.batch = self.batch, Batch()
            if batch.empty():
                return
            await self.dbx.run(_commit, batch)
            self.last_commit_ms = now_ms()
            self.commits += 1


def _commit(conn: sqlite3.Connection, b: Batch) -> None:
    with db.tx(conn):
        if b.readings:
            conn.executemany(
                "INSERT OR REPLACE INTO readings(channel_id, ts, value, quality) VALUES (?, ?, ?, ?)", b.readings
            )
        for cid, r in b.latest.items():
            conn.execute(
                "INSERT INTO channel_latest(channel_id, ts, value, quality, alarm, alarm_since, fault_since, detail) "
                "VALUES (:cid, :ts, :value, :quality, :alarm, :alarm_since, :fault_since, :detail) "
                "ON CONFLICT(channel_id) DO UPDATE SET ts = excluded.ts, value = excluded.value, "
                "quality = excluded.quality, alarm = excluded.alarm, alarm_since = excluded.alarm_since, "
                "fault_since = excluded.fault_since, detail = excluded.detail",
                {"cid": cid, "alarm": None, "alarm_since": None, "fault_since": None, "detail": None, **r},
            )
        for did, r in b.status.items():
            row = {
                "did": did,
                "since": None,
                "last_ok_ts": None,
                "last_error": None,
                "last_error_kind": None,
                "last_error_ts": None,
                "consecutive_failures": 0,
                "last_rtt_ms": None,
                "counters": {},
                **r,
            }
            row["counters"] = json.dumps(row["counters"])
            conn.execute(
                "INSERT INTO device_status(device_id, state, since, last_ok_ts, last_error, last_error_kind, "
                "last_error_ts, consecutive_failures, last_rtt_ms, counters, updated_at) VALUES (:did, :state, :since, "
                ":last_ok_ts, :last_error, :last_error_kind, :last_error_ts, :consecutive_failures, :last_rtt_ms, "
                ":counters, :updated_at) ON CONFLICT(device_id) DO UPDATE SET state = excluded.state, "
                "since = excluded.since, last_ok_ts = excluded.last_ok_ts, last_error = excluded.last_error, "
                "last_error_kind = excluded.last_error_kind, last_error_ts = excluded.last_error_ts, "
                "consecutive_failures = excluded.consecutive_failures, last_rtt_ms = excluded.last_rtt_ms, "
                "counters = excluded.counters, updated_at = excluded.updated_at",
                {"updated_at": now_ms(), **row},
            )
        if b.events:
            conn.executemany("INSERT INTO device_events(device_id, ts, type, detail) VALUES (?, ?, ?, ?)", b.events)
        for (did, ts), s in b.stats.items():
            conn.execute(
                "INSERT INTO device_stats_5m(device_id, ts, requests, ok, timeout, crc, exception, sensor, io, rtt_sum, "
                "rtt_n) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(device_id, ts) DO UPDATE SET "
                "requests = requests + excluded.requests, ok = ok + excluded.ok, timeout = timeout + excluded.timeout, "
                "crc = crc + excluded.crc, exception = exception + excluded.exception, sensor = sensor + excluded.sensor, "
                "io = io + excluded.io, rtt_sum = rtt_sum + excluded.rtt_sum, rtt_n = rtt_n + excluded.rtt_n",
                (did, ts, *(s[k] for k in STAT_KEYS)),
            )
        if b.frames:
            conn.executemany(
                "INSERT INTO frame_log(connection_id, ts, dir, hex, note) VALUES (?, ?, ?, ?, ?)", b.frames
            )

"""Worker cho một kết nối: asyncio task gửi request tuần tự, chọn thiết bị đến hạn theo chu kỳ riêng (spec mục 5)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..core.decode import Decoded, alarm_state, evaluate
from ..core.repo import RuntimeChannel, RuntimeConnection, RuntimeDevice
from ..core.timeutil import now_ms
from .bus import BusClient, BusError

if TYPE_CHECKING:
    from .service import Collector

log = logging.getLogger("greenhouse.collector")

OFFLINE_AFTER = 3
MAX_BACKOFF_S = 60
IO_RETRY_S = 5


@dataclass
class ChanState:
    alarm: str | None = None
    alarm_since: int | None = None
    fault_since: int | None = None


@dataclass
class DevState:
    state: str = "unknown"
    since: int | None = None
    fails: int = 0
    last_ok_ts: int | None = None
    last_error: str | None = None
    last_error_kind: str | None = None
    last_error_ts: int | None = None
    rtt: float | None = None
    counters: dict[str, float] = field(default_factory=dict)


class ConnectionWorker:
    def __init__(self, svc: Collector, rc: RuntimeConnection):
        self.svc = svc
        self.rc = rc
        self.devices: dict[int, RuntimeDevice] = {d.id: d for d in rc.devices}
        start = time.monotonic()
        self.next_due: dict[int, float] = {d.id: start + i * 0.3 for i, d in enumerate(rc.devices)}
        self.durations: dict[int, float] = {}
        self.bus = BusClient(rc.type, rc.params, on_frame=self.on_frame)
        self.lock = asyncio.Lock()
        self.job_pending = 0
        self.paused: str | None = None
        self.heartbeat = time.monotonic()
        self.overload: str | None = None
        self.io_error: str | None = None
        self.task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()

    @property
    def id(self) -> int:
        return self.rc.id

    # --- vòng đời ----------------------------------------------------------------------

    def start(self) -> None:
        self.task = asyncio.create_task(self.run(), name=f"worker-{self.id}")

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
        self.bus.close()

    def update(self, rc: RuntimeConnection) -> None:
        """Cùng tham số cổng: chỉ cập nhật danh sách thiết bị, kênh, ngưỡng."""
        self.rc = rc
        now = time.monotonic()
        new = {d.id: d for d in rc.devices}
        for did in new:
            self.next_due.setdefault(did, now + 0.2)
        for did in list(self.next_due):
            if did not in new:
                del self.next_due[did]
                self.durations.pop(did, None)
        self.devices = new
        self._wake.set()

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._wake.wait(), max(0.01, seconds))
        except TimeoutError:
            pass
        self._wake.clear()

    async def run(self) -> None:
        while True:
            self.heartbeat = time.monotonic()
            if self.job_pending or self.lock.locked():
                await self._sleep(0.5)
                continue
            if not self.devices:
                await self._sleep(1.0)
                continue
            dev = min(self.devices.values(), key=lambda d: self.next_due.get(d.id, 0.0))
            due = self.next_due.get(dev.id, 0.0)
            delay = due - time.monotonic()
            if delay > 0:
                await self._sleep(min(delay, 1.0))
                continue
            async with self.lock:
                lateness = time.monotonic() - due
                try:
                    err = await self.poll(dev)
                except Exception:
                    log.exception("Lỗi khi đọc %s", dev.name)
                    err = None
            self._schedule(dev, err, due, lateness)

    def _schedule(self, dev: RuntimeDevice, err: BusError | None, due: float, lateness: float) -> None:
        st = self.svc.dev_state(dev.id)
        now = time.monotonic()
        if st.fails >= OFFLINE_AFTER:
            interval = min(MAX_BACKOFF_S, dev.poll_s * 2 ** (st.fails - OFFLINE_AFTER + 1))
            nxt = now + interval
        else:
            nxt = due + dev.poll_s
            if nxt < now:
                nxt = now + dev.poll_s
        self.next_due[dev.id] = nxt
        if err is not None and err.kind == "io":
            self.io_error = err.message
            for did in self.next_due:
                self.next_due[did] = max(self.next_due[did], now + IO_RETRY_S)
        elif err is None:
            self.io_error = None
        # Cảnh báo bus quá tải thay vì âm thầm trễ (spec mục 5).
        cycle_s = sum(self.durations.get(d, 0.0) for d in self.devices) / 1000
        shortest = min(d.poll_s for d in self.devices.values())
        if cycle_s > shortest:
            self.overload = f"Vòng đọc {cycle_s:.1f} s dài hơn chu kỳ {shortest} s"
        elif lateness > dev.poll_s and st.fails < OFFLINE_AFTER:
            self.overload = f"{dev.name} đọc trễ {lateness:.1f} s so với chu kỳ {dev.poll_s} s"
        elif lateness < 1:
            self.overload = None

    # --- đọc thiết bị -------------------------------------------------------------------

    async def poll(self, dev: RuntimeDevice) -> BusError | None:
        started = time.perf_counter()
        results: list[tuple[RuntimeChannel, Decoded]] = []
        rtts: list[float] = []
        err: BusError | None = None
        try:
            for b in dev.blocks:
                rr = await self.bus.read(dev.unit_id, b.fc, b.start, b.count)
                rtts.append(rr.rtt_ms)
                for ch in b.channels:
                    results.append((ch, evaluate(ch.cdef, rr.regs, b.start)))
        except BusError as e:
            err = e
        self.durations[dev.id] = (time.perf_counter() - started) * 1000
        self.record(dev, now_ms(), results, err, rtts)
        return err

    def record(
        self,
        dev: RuntimeDevice,
        ts: int,
        results: list[tuple[RuntimeChannel, Decoded]],
        err: BusError | None,
        rtts: list[float],
    ) -> None:
        """Mọi lần đọc lỗi không ghi bản ghi đo: chỉ cập nhật trạng thái, bộ đếm và sự kiện (spec mục 5)."""
        w = self.svc.writer
        st = self.svc.dev_state(dev.id)
        c = st.counters
        c["requests"] = c.get("requests", 0) + 1
        if err is None:
            faults: list[str] = []
            for ch, d in results:
                cs = self.svc.ch_state(ch.id)
                if d.quality == "sensor_fault":
                    if cs.fault_since is None:
                        cs.fault_since = ts
                        w.event(dev.id, ts, "sensor_fault", f"{ch.label}: {d.detail}")
                    cs.alarm, cs.alarm_since = None, None
                    w.latest(
                        ch.id, ts=ts, value=None, quality="sensor_fault", fault_since=cs.fault_since, detail=d.detail
                    )
                    faults.append(f"{ch.label}: {d.detail}")
                    continue
                if cs.fault_since is not None:
                    cs.fault_since = None
                    w.event(dev.id, ts, "sensor_ok", ch.label)
                assert d.value is not None
                if d.quality == "good":
                    w.reading(ch.id, ts, d.value, 0)
                    alarm = alarm_state(d.value, ch.alarm_low, ch.alarm_high)
                    if alarm != cs.alarm:
                        cs.alarm, cs.alarm_since = alarm, ts if alarm else None
                    w.latest(ch.id, ts=ts, value=d.value, quality="good", alarm=cs.alarm, alarm_since=cs.alarm_since)
                else:
                    # out_of_range: vẫn lưu để điều tra, không gộp, không xét ngưỡng
                    w.reading(ch.id, ts, d.value, 1)
                    cs.alarm, cs.alarm_since = None, None
                    w.latest(ch.id, ts=ts, value=d.value, quality="out_of_range", detail=d.detail)
            if st.state != "online":
                w.event(dev.id, ts, "online", None if st.state == "unknown" else f"Sau {st.fails} lần đọc lỗi")
                st.state, st.since = "online", ts
            st.fails = 0
            st.last_ok_ts = ts
            st.rtt = sum(rtts) / len(rtts) if rtts else None
            if faults:
                st.last_error, st.last_error_kind, st.last_error_ts = "; ".join(faults), "sensor", ts
                c["sensor"] = c.get("sensor", 0) + 1
            c["ok"] = c.get("ok", 0) + (0 if faults else 1)
            c["rtt_sum"] = c.get("rtt_sum", 0) + sum(rtts)
            c["rtt_n"] = c.get("rtt_n", 0) + len(rtts)
            w.stats(
                dev.id,
                ts,
                requests=1,
                ok=0 if faults else 1,
                sensor=1 if faults else 0,
                rtt_sum=sum(rtts),
                rtt_n=len(rtts),
            )
        else:
            st.fails += 1
            st.last_error, st.last_error_kind, st.last_error_ts = err.message, err.kind, ts
            c[err.kind] = c.get(err.kind, 0) + 1
            if st.fails >= OFFLINE_AFTER and st.state != "offline":
                st.state, st.since = "offline", ts
                w.event(dev.id, ts, "offline", err.message)
            w.stats(dev.id, ts, requests=1, **{err.kind: 1})
        w.status(
            dev.id,
            state=st.state,
            since=st.since,
            last_ok_ts=st.last_ok_ts,
            last_error=st.last_error,
            last_error_kind=st.last_error_kind,
            last_error_ts=st.last_error_ts,
            consecutive_failures=st.fails,
            last_rtt_ms=st.rtt,
            counters=dict(c),
        )

    # --- log frame và lệnh từ web -------------------------------------------------------

    def on_frame(self, direction: str, data: bytes, note: str | None) -> None:
        if self.svc.frame_log_until.get(self.id, 0) > now_ms():
            self.svc.writer.frame(self.id, now_ms(), direction, data.hex(" ").upper(), note)

    @asynccontextmanager
    async def exclusive(self, reason: str) -> AsyncIterator[None]:
        """Giữ bus cho một lệnh (đọc thử, quét, đổi địa chỉ): polling trên bus này tạm dừng, bus khác vẫn chạy."""
        self.job_pending += 1
        try:
            await self.lock.acquire()
        finally:
            self.job_pending -= 1
        self.paused = reason
        self.bus.close()
        try:
            yield
        finally:
            self.paused = None
            self.bus.close()
            self.lock.release()
            now = time.monotonic()
            for did in self.next_due:
                self.next_due[did] = min(self.next_due[did], now + 0.3)
            self._wake.set()

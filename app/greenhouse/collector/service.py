"""Dịch vụ collector: worker cho từng kết nối, ghi lô, gộp 5 phút, backup, watchdog, API nội bộ."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import socket
import sqlite3
import time
from pathlib import Path
from typing import Any

from .. import __version__, sim  # noqa: F401  (sim đăng ký cổng ảo sim:// với pyserial)
from ..core import config, db
from ..core.models import RtuParams, TcpParams, TemplateDef, parse_params
from ..core.repo import RuntimeConnection, load_runtime, template_defs
from ..core.timeutil import now_ms
from . import maintenance
from .jobs import Job
from .worker import ChanState, ConnectionWorker, DevState
from .writer import DbExecutor, Writer

log = logging.getLogger("greenhouse.collector")

WORKER_STALE_S = 60  # worker treo quá 60 giây thì ngừng báo sống để systemd khởi động lại collector
MAX_JOBS = 20


def sd_notify(message: str) -> None:
    """Báo systemd (Type=notify, WatchdogSec). Bỏ qua khi không chạy dưới systemd."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr or not hasattr(socket, "AF_UNIX"):
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.sendall(message.encode())
    except OSError:
        pass


class Collector:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path
        self.dbx = DbExecutor(db_path)
        self.writer = Writer(self.dbx)
        self.workers: dict[int, ConnectionWorker] = {}
        self.runtime: dict[int, RuntimeConnection] = {}
        self._saved: dict[int, tuple[str, RtuParams | TcpParams]] = {}
        self._templates: dict[int, TemplateDef] = {}
        self._dev: dict[int, DevState] = {}
        self._ch: dict[int, ChanState] = {}
        self.jobs: dict[int, Job] = {}
        self._job_seq = 0
        self.frame_log_until: dict[int, int] = {}
        self.started_ms = now_ms()
        self.clock_synced: bool | None = None
        self.clock_warning: str | None = None
        self.stopping = asyncio.Event()
        self._reload_lock = asyncio.Lock()
        self._tasks: list[asyncio.Task[Any]] = []

    # --- trạng thái dùng chung cho worker và lệnh ---------------------------------------

    def dev_state(self, device_id: int) -> DevState:
        return self._dev.setdefault(device_id, DevState())

    def ch_state(self, channel_id: int) -> ChanState:
        return self._ch.setdefault(channel_id, ChanState())

    def saved_connection(self, cid: int) -> tuple[str, RtuParams | TcpParams] | None:
        return self._saved.get(cid)

    def template(self, tid: int) -> TemplateDef | None:
        return self._templates.get(tid)

    def worker_for(self, cid: Any, params: RtuParams | TcpParams) -> ConnectionWorker | None:
        """Worker đang giữ kết nối này, hoặc đang giữ cùng cổng serial (cổng serial chỉ mở được một lần)."""
        if cid is not None and int(cid) in self.workers:
            return self.workers[int(cid)]
        if isinstance(params, RtuParams):
            for w in self.workers.values():
                if isinstance(w.rc.params, RtuParams) and w.rc.params.port == params.port:
                    return w
        return None

    def new_job(self, kind: str, cid: int) -> Job:
        self._job_seq += 1
        job = Job(self._job_seq, kind, cid)
        self.jobs[job.id] = job
        for old in sorted(self.jobs)[:-MAX_JOBS]:
            if self.jobs[old].status != "running":
                del self.jobs[old]
        return job

    # --- nạp cấu hình -------------------------------------------------------------------

    def _load_all(self, conn: sqlite3.Connection) -> tuple[Any, ...]:
        saved = {
            r["id"]: (r["type"], parse_params(r["type"], json.loads(r["params"])))
            for r in conn.execute("SELECT id, type, params FROM connections")
        }
        return load_runtime(conn), saved, template_defs(conn)

    def _load_states(self, conn: sqlite3.Connection) -> None:
        for r in conn.execute("SELECT * FROM device_status"):
            self._dev[r["device_id"]] = DevState(
                state=r["state"],
                since=r["since"],
                fails=r["consecutive_failures"],
                last_ok_ts=r["last_ok_ts"],
                last_error=r["last_error"],
                last_error_kind=r["last_error_kind"],
                last_error_ts=r["last_error_ts"],
                rtt=r["last_rtt_ms"],
                counters={},
            )
        for r in conn.execute("SELECT * FROM channel_latest"):
            self._ch[r["channel_id"]] = ChanState(r["alarm"], r["alarm_since"], r["fault_since"])

    async def reload(self) -> dict[str, Any]:
        """Chỉ khởi động lại worker của kết nối bị đổi tham số cổng; kết nối khác chỉ cập nhật thiết bị."""
        async with self._reload_lock:
            runtime, saved, templates = await self.dbx.run(self._load_all)
            self.runtime, self._saved, self._templates = runtime, saved, templates
            restarted: list[int] = []
            for cid, w in list(self.workers.items()):
                rc = runtime.get(cid)
                if rc is None or rc.signature != w.rc.signature:
                    await w.stop()
                    del self.workers[cid]
                    if rc is not None:
                        restarted.append(cid)
                else:
                    w.update(rc)
            for cid, rc in runtime.items():
                if cid not in self.workers:
                    w = ConnectionWorker(self, rc)
                    self.workers[cid] = w
                    w.start()
            log.info("Nạp cấu hình: %d kết nối đang bật", len(runtime))
            return {"connections": len(runtime), "restarted": restarted}

    # --- trạng thái -----------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        workers = []
        for cid, w in self.workers.items():
            workers.append(
                {
                    "connection_id": cid,
                    "name": w.rc.name,
                    "state": "paused" if w.paused else "error" if w.io_error else "running",
                    "paused_reason": w.paused,
                    "error": w.io_error,
                    "overload": w.overload,
                    "cycle_ms": round(sum(w.durations.get(d, 0.0) for d in w.devices), 1),
                    "devices": len(w.devices),
                    "heartbeat_age_s": round(now - w.heartbeat, 1),
                    "frame_log_until": self.frame_log_until.get(cid),
                }
            )
        return {
            "version": __version__,
            "pid": os.getpid(),
            "started_at": self.started_ms,
            "last_commit_at": self.writer.last_commit_ms,
            "commits": self.writer.commits,
            "clock_synced": self.clock_synced,
            "clock_warning": self.clock_warning,
            "workers": workers,
            "jobs": [j.to_dict() for j in self.jobs.values() if j.status == "running"],
        }

    def set_frame_log(self, cid: int, enabled: bool, minutes: int = 10) -> int | None:
        if enabled:
            self.frame_log_until[cid] = now_ms() + minutes * 60_000
        else:
            self.frame_log_until.pop(cid, None)
        return self.frame_log_until.get(cid)

    # --- tác vụ nền -----------------------------------------------------------------------

    async def _maintenance_loop(self) -> None:
        last_prune = 0.0
        while True:
            try:
                await self.dbx.run(maintenance.aggregate)
                if time.monotonic() - last_prune > 3600:
                    await self.dbx.run(maintenance.prune)
                    last_prune = time.monotonic()
                if await self.dbx.run(maintenance.backup_due):
                    await asyncio.to_thread(maintenance.run_backup, self.db_path)
            except Exception:
                log.exception("Lỗi bảo trì CSDL")
            await asyncio.sleep(30)

    async def _clock_loop(self) -> None:
        while True:
            synced = await asyncio.to_thread(maintenance.clock_synced)
            if self.clock_synced is None and synced is False and self.writer.commits == 0:
                self.clock_warning = "Đồng hồ hệ thống chưa đồng bộ khi bắt đầu ghi dữ liệu"
            self.clock_synced = synced
            await asyncio.sleep(600)

    async def _watchdog_loop(self) -> None:
        """Báo sống cho systemd khi mọi worker còn quay vòng lặp (kể cả lúc chờ thử lại)."""
        while True:
            now = time.monotonic()
            stale = [w.rc.name for w in self.workers.values() if now - w.heartbeat > WORKER_STALE_S]
            if stale:
                log.error("Worker treo: %s; ngừng báo watchdog", ", ".join(stale))
            else:
                sd_notify("WATCHDOG=1")
            await asyncio.sleep(5)

    # --- vòng đời -------------------------------------------------------------------------

    async def start(self) -> None:
        await self.dbx.run(db.migrate)
        await self.dbx.run(self._load_states)
        await self.reload()
        for coro in (self.writer.run(), self._maintenance_loop(), self._clock_loop(), self._watchdog_loop()):
            self._tasks.append(asyncio.create_task(coro))

    async def stop(self) -> None:
        for w in list(self.workers.values()):
            await w.stop()
        self.workers.clear()
        for job in self.jobs.values():
            if job.task is not None and not job.task.done():
                job.task.cancel()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        try:
            await self.writer.flush()
        except Exception:
            log.exception("Không ghi được lô cuối")
        self.dbx.shutdown()


def _restrict_socket(path: str) -> None:
    """Chỉ group của dịch vụ web truy cập socket (spec mục 10)."""
    if os.path.exists(path):
        os.chmod(path, 0o660)


async def serve(db_path: Path | None = None) -> None:
    import uvicorn

    from .api import create_api

    svc = Collector(db_path)
    await svc.start()
    ep = config.collector_endpoint()
    if ep.kind == "unix":
        Path(ep.path).parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(ep.path)
        ucfg = uvicorn.Config(create_api(svc), uds=ep.path, log_level="warning", lifespan="off", access_log=False)
    else:
        ucfg = uvicorn.Config(
            create_api(svc), host=ep.host, port=ep.port, log_level="warning", lifespan="off", access_log=False
        )
    server = uvicorn.Server(ucfg)
    server.capture_signals = contextlib.nullcontext  # type: ignore[method-assign,assignment]
    api_task = asyncio.create_task(server.serve())

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, svc.stopping.set)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(svc.stopping.set))

    # uvicorn không có sự kiện "đã nghe", chỉ có cờ started nên phải thăm dò.
    while not server.started and not api_task.done():  # noqa: ASYNC110
        await asyncio.sleep(0.05)
    if ep.kind == "unix":
        await asyncio.to_thread(_restrict_socket, ep.path)
    sd_notify("READY=1")
    log.info("Collector sẵn sàng, API nội bộ %s", ep)
    try:
        await svc.stopping.wait()
    finally:
        sd_notify("STOPPING=1")
        server.should_exit = True
        await asyncio.gather(api_task, return_exceptions=True)
        await svc.stop()
        log.info("Collector dừng")

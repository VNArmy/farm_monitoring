"""Luồng realtime (SSE): mỗi 2 giây đọc channel_latest, chỉ đẩy phần thay đổi (spec mục 2, 7).

Sự kiện: snapshot (khi mới kết nối hoặc khi đổi cấu trúc), reading (một kênh), device_status (một thiết bị),
system (collector, cảnh báo, tên site), và riêng cho HMI: hmi_config, reload.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import Request

from ..core import db
from . import collector_client
from .services.overview import compute

log = logging.getLogger("greenhouse.web")

INTERVAL_S = 2.0
KEEPALIVE_S = 15.0

# Trang HMI đang mở (lấy từ kết nối SSE của nó), để trang Cài đặt hiện trạng thái màn hình.
HMI_PRESENCE: dict[int, dict[str, Any]] = {}


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _system(snap: dict[str, Any]) -> dict[str, Any]:
    return {k: snap[k] for k in ("site_name", "timezone", "frontend_version", "collector", "alarms", "zones")}


class Hub:
    def __init__(
        self, frontend_version: Callable[[], str], extra: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    ):
        self.frontend_version = frontend_version
        self.extra = extra  # HMI: thêm cấu hình màn hình vào ảnh chụp
        self.snapshot: dict[str, Any] | None = None
        self.subs: set[asyncio.Queue[str | None]] = set()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def compute(self) -> dict[str, Any]:
        status = await collector_client.status()

        def work() -> dict[str, Any]:
            conn = db.thread_conn()
            snap = compute(conn, status, self.frontend_version())
            if self.extra is not None:
                snap.update(self.extra(snap))
            return snap

        return await asyncio.to_thread(work)

    async def _loop(self) -> None:
        while True:
            try:
                snap = await self.compute()
                events = self.diff(self.snapshot, snap) if self.snapshot is not None else []
                self.snapshot = snap
                for q in list(self.subs):
                    for ev in events:
                        try:
                            q.put_nowait(ev)
                        except asyncio.QueueFull:
                            # Trình duyệt đọc không kịp: ngắt luồng, trình duyệt tự nối lại và nhận snapshot mới.
                            self.subs.discard(q)
                            break
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Không tính được ảnh chụp trạng thái")
            await asyncio.sleep(INTERVAL_S)

    @staticmethod
    def diff(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
        oc = {c["id"]: c for c in old["channels"] + old["derived"]}
        nc = {c["id"]: c for c in new["channels"] + new["derived"]}
        od = {d["id"]: d for d in old["devices"]}
        nd = {d["id"]: d for d in new["devices"]}
        if set(oc) != set(nc) or set(od) != set(nd) or old["zones"] != new["zones"]:
            return [_sse("snapshot", new)]
        events = [_sse("reading", c) for cid, c in nc.items() if c != oc[cid]]
        events += [_sse("device_status", d) for did, d in nd.items() if d != od[did]]
        if _system(old) != _system(new):
            events.append(_sse("system", _system(new)))
        if "hmi" in new and old.get("hmi") != new["hmi"]:
            if old.get("hmi", {}).get("reload_token") != new["hmi"].get("reload_token"):
                events.append(_sse("reload", {"reason": "admin"}))
            events.append(_sse("hmi_config", new["hmi"]))
        return events

    async def stream(self, request: Request, presence: dict[str, Any] | None = None) -> AsyncIterator[str]:
        q: asyncio.Queue[str | None] = asyncio.Queue(maxsize=200)
        self.subs.add(q)
        key = id(q)
        if presence is not None:
            HMI_PRESENCE[key] = {**presence, "connected_since": int(time.time() * 1000)}
        try:
            yield "retry: 3000\n\n"
            snap = self.snapshot or await self.compute()
            yield _sse("snapshot", snap)
            while q in self.subs:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), KEEPALIVE_S)
                except TimeoutError:
                    # Sự kiện có tên (không phải comment) để trang HMI biết Pi vẫn trả lời khi số liệu không đổi.
                    yield _sse("ping", {"now": int(time.time() * 1000)})
                    continue
                if ev is None:
                    break
                yield ev
        finally:
            self.subs.discard(q)
            HMI_PRESENCE.pop(key, None)


def hmi_presence() -> dict[str, Any] | None:
    if not HMI_PRESENCE:
        return None
    return min(HMI_PRESENCE.values(), key=lambda p: p["connected_since"])

"""Web gọi API nội bộ của collector qua Unix socket; web không bao giờ tự mở cổng serial (spec mục 2)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from ..core import config
from ..core.errors import ApiError

log = logging.getLogger("greenhouse.web")

OFFLINE_MESSAGE = "Collector đang dừng nên không chạy được lệnh trên bus. Cấu hình vẫn lưu được."
STATUS_TTL_S = 1.5
CONNECT_TIMEOUT_S = 0.3

_status_cache: tuple[float, dict[str, Any] | None] = (0.0, None)
_shared: tuple[asyncio.AbstractEventLoop, str, httpx.AsyncClient] | None = None


def _client() -> httpx.AsyncClient:
    """Một client dùng lại cho mỗi event loop: tạo AsyncClient mới mỗi lần gọi tốn ~150 ms dựng SSL context ngay trên
    event loop, làm nghẽn SSE và làm timeout nối 0,3 giây của request khác nổ giả (báo collector dừng trong khi vẫn chạy)."""
    global _shared
    loop = asyncio.get_running_loop()
    ep = config.collector_endpoint()
    if _shared is not None and _shared[0] is loop and _shared[1] == str(ep) and not _shared[2].is_closed:
        return _shared[2]
    if ep.kind == "unix":
        transport = httpx.AsyncHTTPTransport(uds=ep.path, retries=1)
        client = httpx.AsyncClient(transport=transport, base_url="http://collector")
    else:
        client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(retries=1), base_url=f"http://{ep.host}:{ep.port}"
        )
    _shared = (loop, str(ep), client)
    return client


async def aclose() -> None:
    """Đóng client dùng chung khi web dừng."""
    global _shared
    if _shared is not None and _shared[0] is asyncio.get_running_loop():
        await _shared[2].aclose()
    _shared = None


async def call(method: str, path: str, body: Any = None, http_timeout: float = 5.0) -> dict[str, Any]:
    # Nối socket nội bộ khi collector chạy là tức thì; Windows mất ~2 giây mới báo cổng loopback đóng.
    timeout = httpx.Timeout(http_timeout, connect=CONNECT_TIMEOUT_S)
    try:
        r = await _client().request(method, path, json=body, timeout=timeout)
    except (httpx.TransportError, OSError) as e:
        log.info("Không gọi được collector %s %s: %r", method, path, e)
        raise ApiError(503, "collector_offline", OFFLINE_MESSAGE) from e
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        err = data.get("error", {}) if isinstance(data, dict) else {}
        raise ApiError(
            r.status_code, err.get("code", "collector_error"), err.get("message", "Collector báo lỗi"), err.get("field")
        )
    return data


async def status(fresh: bool = False) -> dict[str, Any] | None:
    """Trạng thái collector, None khi collector không chạy. Cache ngắn vì SSE hỏi mỗi 2 giây."""
    global _status_cache
    ts, cached = _status_cache
    if not fresh and time.monotonic() - ts < STATUS_TTL_S:
        return cached
    try:
        result: dict[str, Any] | None = await call("GET", "/status", http_timeout=1.5)
    except ApiError:
        result = None
    _status_cache = (time.monotonic(), result)
    return result


async def reload() -> None:
    """Sau khi lưu cấu hình. Collector dừng thì bỏ qua: nó nạp cấu hình khi chạy lại."""
    try:
        await call("POST", "/reload", http_timeout=5.0)
    except ApiError as e:
        log.info("Không báo được collector nạp lại cấu hình: %s", e.message)

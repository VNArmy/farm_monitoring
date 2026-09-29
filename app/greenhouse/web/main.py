"""Chạy hai server uvicorn trong một process: web app 127.0.0.1:8080 (sau Caddy) và HMI 127.0.0.1:8081."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

import uvicorn

from ..core import config
from .app import create_app

log = logging.getLogger("greenhouse.web")


async def serve() -> None:
    main = uvicorn.Server(
        uvicorn.Config(
            create_app("main"),
            host=config.WEB_HOST,
            port=config.WEB_PORT,
            proxy_headers=True,
            forwarded_allow_ips="127.0.0.1",
            access_log=False,
            log_level="info",
        )
    )
    hmi = uvicorn.Server(
        uvicorn.Config(
            create_app("hmi"),
            host=config.HMI_HOST,
            port=config.HMI_PORT,
            access_log=False,
            log_level="warning",
        )
    )
    stop = asyncio.Event()
    for server in (main, hmi):
        server.capture_signals = contextlib.nullcontext  # type: ignore[method-assign,assignment]
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    tasks = [asyncio.create_task(main.serve()), asyncio.create_task(hmi.serve())]
    stopper = asyncio.create_task(stop.wait())
    await asyncio.wait([*tasks, stopper], return_when=asyncio.FIRST_COMPLETED)
    main.should_exit = hmi.should_exit = True
    stopper.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def main() -> None:
    log.info(
        "Web app http://%s:%d · HMI http://%s:%d/hmi",
        config.WEB_HOST,
        config.WEB_PORT,
        config.HMI_HOST,
        config.HMI_PORT,
    )
    asyncio.run(serve())

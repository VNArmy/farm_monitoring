"""API nội bộ của collector trên Unix socket /run/greenhouse/collector.sock (spec mục 5).

GET /status, POST /reload, POST /test-read, POST /test-connection, POST /scan, GET /jobs/{id},
POST /jobs/{id}/cancel, POST /set-address, POST /frame-log. Không lộ ra mạng.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..core.errors import ApiError, not_found
from . import jobs

if TYPE_CHECKING:
    from .service import Collector


def create_api(svc: Collector) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(exc.to_dict(), status_code=exc.status)

    @app.exception_handler(ValidationError)
    async def validation_error(request: Request, exc: ValidationError) -> JSONResponse:
        e: dict[str, Any] = dict(exc.errors()[0]) if exc.errors() else {}
        field = ".".join(str(x) for x in e.get("loc", ()))
        return JSONResponse(
            {"error": {"code": "invalid", "message": f"{field}: {e.get('msg', 'không hợp lệ')}", "field": field}},
            status_code=400,
        )

    @app.get("/status")
    async def status() -> dict[str, Any]:
        return svc.status()

    @app.post("/reload")
    async def reload() -> dict[str, Any]:
        return await svc.reload()

    @app.post("/test-read")
    async def test_read(body: dict[str, Any]) -> dict[str, Any]:
        return await jobs.test_read(svc, body)

    @app.post("/test-connection")
    async def test_connection(body: dict[str, Any]) -> dict[str, Any]:
        return await jobs.test_connection(svc, body)

    @app.post("/scan")
    async def scan(body: dict[str, Any]) -> dict[str, Any]:
        job = jobs.start_scan(svc, int(body["connection_id"]), body)
        return {"job_id": job.id}

    @app.get("/jobs/{job_id}")
    async def job(job_id: int) -> dict[str, Any]:
        j = svc.jobs.get(job_id)
        if j is None:
            raise not_found("Không tìm thấy job")
        return j.to_dict()

    @app.post("/jobs/{job_id}/cancel")
    async def cancel(job_id: int) -> dict[str, Any]:
        j = svc.jobs.get(job_id)
        if j is None:
            raise not_found("Không tìm thấy job")
        j.cancel = True
        return j.to_dict()

    @app.post("/set-address")
    async def set_address(body: dict[str, Any]) -> dict[str, Any]:
        return await jobs.set_address(svc, int(body["connection_id"]), body)

    @app.post("/frame-log")
    async def frame_log(body: dict[str, Any]) -> dict[str, Any]:
        until = svc.set_frame_log(int(body["connection_id"]), bool(body.get("enabled")))
        return {"connection_id": int(body["connection_id"]), "until": until}

    return app

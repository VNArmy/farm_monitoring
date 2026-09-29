"""Trang HMI chỉ đọc, chỉ có trên cổng 127.0.0.1:8081, không đăng nhập (spec mục 7, 9)."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from ...core import db
from ...core.errors import ApiError
from ...core.timeutil import now_ms
from ..auth import get_db
from ..services.readings import sparklines
from .data import readings_response, stream_response

router = APIRouter(prefix="/api/hmi", tags=["HMI"])


@router.get("/overview")
async def overview(request: Request) -> dict[str, Any]:
    hub = request.app.state.hub
    return hub.snapshot or await hub.compute()


@router.get("/stream")
async def stream(request: Request, w: int = 0, h: int = 0) -> StreamingResponse:
    presence = {"width": w, "height": h, "user_agent": request.headers.get("user-agent", "")[:200]}
    return stream_response(request.app.state.hub.stream(request, presence))


@router.get("/sparklines", summary="Xu hướng 1 giờ trên thẻ HMI; luôn có, không phụ thuộc quyền xem biểu đồ")
def spark(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return sparklines(conn, now_ms())


@router.get("/readings")
def readings(
    channels: str,
    start: int = Query(alias="from"),
    end: int = Query(alias="to"),
    max_points: int = Query(2000, ge=10, le=5000),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    if not db.get_setting(conn, "hmi_allow_charts"):
        raise ApiError(403, "charts_disabled", "Biểu đồ trên HMI đang tắt")
    return readings_response(conn, channels, start, end, max_points)

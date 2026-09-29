"""Dữ liệu cho viewer (spec mục 9): /api/overview, /api/stream, /api/readings, /api/export.csv, /api/devices, /api/channels."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from ...core import db
from ...core.errors import invalid
from ...core.timeutil import now_ms, zone
from ..auth import User, get_db, require_viewer
from ..services.readings import EXPORT_RES, export_csv, export_estimate, history, sparklines

router = APIRouter(prefix="/api", tags=["Dữ liệu"])

MAX_CHANNELS = 8
MAX_SPAN_MS = 400 * 86_400_000


def parse_channels(channels: str, start: int, end: int) -> list[int]:
    try:
        ids = [int(x) for x in channels.split(",") if x.strip()]
    except ValueError as e:
        raise invalid("Danh sách kênh không hợp lệ", "channels") from e
    if not ids:
        raise invalid("Chưa chọn kênh", "channels")
    if len(ids) > MAX_CHANNELS:
        raise invalid(f"Tối đa {MAX_CHANNELS} kênh", "channels")
    if end <= start:
        raise invalid("Thời điểm kết thúc phải sau thời điểm bắt đầu", "to")
    if end - start > MAX_SPAN_MS:
        raise invalid("Khoảng thời gian tối đa 400 ngày", "from")
    return list(dict.fromkeys(ids))


def readings_response(conn: sqlite3.Connection, channels: str, start: int, end: int, max_points: int) -> dict[str, Any]:
    ids = parse_channels(channels, start, end)
    return history(conn, ids, start, end, max_points, db.get_setting(conn, "timezone"), now_ms())


def stream_response(gen: Any) -> StreamingResponse:
    return StreamingResponse(
        gen, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.get("/overview", summary="Giá trị mới nhất và trạng thái mọi thiết bị")
async def overview(request: Request, user: User = Depends(require_viewer)) -> dict[str, Any]:
    hub = request.app.state.hub
    return hub.snapshot or await hub.compute()


@router.get("/stream", summary="SSE: sự kiện snapshot, reading, device_status, system")
async def stream(request: Request, user: User = Depends(require_viewer)) -> StreamingResponse:
    return stream_response(request.app.state.hub.stream(request))


@router.get("/readings", summary="Lịch sử theo kênh; server chọn bucket để mỗi kênh tối đa max_points điểm")
def readings(
    channels: str,
    start: int = Query(alias="from", description="epoch mili giây UTC"),
    end: int = Query(alias="to", description="epoch mili giây UTC"),
    max_points: int = Query(2000, ge=10, le=5000),
    user: User = Depends(require_viewer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return readings_response(conn, channels, start, end, max_points)


@router.get("/sparklines", summary="Đường xu hướng 1 giờ của mọi kênh, trung bình mỗi phút")
def spark(user: User = Depends(require_viewer), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    return sparklines(conn, now_ms())


@router.get("/export/estimate", summary="Số dòng ước tính cho từng độ phân giải")
def estimate(
    channels: str,
    start: int = Query(alias="from"),
    end: int = Query(alias="to"),
    user: User = Depends(require_viewer),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, int]:
    ids = parse_channels(channels, start, end)
    return export_estimate(conn, ids, start, end, db.get_setting(conn, "timezone"))


@router.get("/export.csv", summary="Xuất CSV theo luồng; resolution là raw, 5m, 1h hoặc 1d")
def export(
    channels: str,
    start: int = Query(alias="from"),
    end: int = Query(alias="to"),
    resolution: str = "1h",
    user: User = Depends(require_viewer),
    conn: sqlite3.Connection = Depends(get_db),
) -> StreamingResponse:
    if resolution not in EXPORT_RES:
        raise invalid("Độ phân giải là raw, 5m, 1h hoặc 1d", "resolution")
    ids = parse_channels(channels, start, end)
    tz = db.get_setting(conn, "timezone")
    z = zone(tz)
    name = "nha-kinh_{}_{}_{}.csv".format(
        datetime.fromtimestamp(start / 1000, z).strftime("%Y%m%d-%H%M"),
        datetime.fromtimestamp(end / 1000, z).strftime("%Y%m%d-%H%M"),
        resolution,
    )
    stream_conn = db.connect()  # kết nối riêng: luồng chạy sau khi request kết thúc

    def gen() -> Any:
        try:
            yield from export_csv(stream_conn, ids, start, end, resolution, tz)
        finally:
            stream_conn.close()

    return StreamingResponse(
        gen(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )


@router.get("/devices", summary="Thiết bị và trạng thái (chỉ đọc)")
async def devices(request: Request, user: User = Depends(require_viewer)) -> list[dict[str, Any]]:
    snap = request.app.state.hub.snapshot or await request.app.state.hub.compute()
    return snap["devices"]


@router.get("/channels", summary="Danh mục kênh (chỉ đọc)")
async def channels(request: Request, user: User = Depends(require_viewer)) -> list[dict[str, Any]]:
    snap = request.app.state.hub.snapshot or await request.app.state.hub.compute()
    return snap["channels"] + snap["derived"]

"""Bản đồ trại (docs/spec-ban-do.md mục 5): tọa độ và file nền PMTiles, chỉ có ở cổng web."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ...core import config, db
from ...core.errors import not_found
from ..auth import User, get_db, require_viewer

router = APIRouter(prefix="/api/map", tags=["Bản đồ"])

BASEMAP_URL = "/api/map/basemap.pmtiles"


@router.get("/config", summary="Điểm trại và file nền, null nếu chưa có")
def map_config(user: User = Depends(require_viewer), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    s = db.get_settings(conn)
    lat, lng = s["site_lat"], s["site_lng"]
    # Kiểm tra file ở mỗi request: cài xong là dùng được, không phải khởi động lại dịch vụ.
    p = config.basemap_path()
    return {
        "site": None if lat is None or lng is None else {"name": s["site_name"], "lat": lat, "lng": lng},
        "basemap": {"url": BASEMAP_URL, "size_bytes": p.stat().st_size} if p.is_file() else None,
    }


@router.get("/basemap.pmtiles", summary="File nền, đọc theo Range")
def basemap(user: User = Depends(require_viewer)) -> FileResponse:
    p = config.basemap_path()
    if not p.is_file():
        raise not_found("Chưa cài file bản đồ")
    # Ghi rõ kiểu: Caddy nén text/*, mà phản hồi đã nén thì không đọc theo Range được.
    return FileResponse(p, media_type="application/octet-stream", headers={"Cache-Control": "private, max-age=86400"})

"""Cấu hình màn hình HMI: bố cục, thẻ và thứ tự, biểu đồ, địa chỉ web app cho mã QR (spec mục 7, 8.7)."""

from __future__ import annotations

import socket
import sqlite3
from typing import Any

from ...core import db

# Thứ tự thẻ mặc định: nhiệt độ, độ ẩm, CO2, ánh sáng, tốc độ gió, hệ thống; VPD tắt.
DEFAULT_KEY_ORDER = ["temperature", "humidity", "co2", "illuminance", "wind_speed"]


def lan_url(settings: dict[str, Any]) -> str:
    url = (settings.get("public_url") or "").strip()
    if url:
        return url
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))  # không gửi gói nào, chỉ để hỏi địa chỉ LAN
            ip = s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        ip = socket.gethostname() + ".local"
    return f"https://{ip}"


def default_cards(snap: dict[str, Any]) -> list[str]:
    def rank(c: dict[str, Any]) -> tuple[int, int, int]:
        k = c["key"]
        return (
            DEFAULT_KEY_ORDER.index(k) if k in DEFAULT_KEY_ORDER else len(DEFAULT_KEY_ORDER),
            c["device_id"],
            c["id"],
        )

    ids = [f"ch:{c['id']}" for c in sorted(snap["channels"], key=rank)]
    return ids + ["system"] + [d["id"] for d in snap["derived"]]


def effective_cards(settings: dict[str, Any], snap: dict[str, Any]) -> list[dict[str, Any]]:
    available = default_cards(snap)
    saved = [c for c in (settings.get("hmi_cards") or []) if c.get("id") in available]
    seen = {c["id"] for c in saved}
    out = [{"id": c["id"], "visible": bool(c.get("visible", True))} for c in saved]
    for a in available:
        if a not in seen:
            out.append({"id": a, "visible": not a.startswith("vpd:")})
    return out


def hmi_config(conn: sqlite3.Connection, snap: dict[str, Any]) -> dict[str, Any]:
    s = db.get_settings(conn)
    return {
        "layout": s["hmi_layout"],
        "cards": effective_cards(s, snap),
        "allow_charts": bool(s["hmi_allow_charts"]),
        "lan_url": lan_url(s),
        "reload_token": s["hmi_reload_token"],
    }

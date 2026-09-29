"""Ảnh chụp trạng thái hiện tại cho trang tổng quan, HMI và luồng SSE (spec mục 7)."""

from __future__ import annotations

import math
import sqlite3
from typing import Any

from ...core import db
from ...core.repo import template_defs
from ...core.timeutil import now_ms

STALE_CYCLES = 3
VPD_SCALE = (0.0, 2.5)

_SQL = """
SELECT ch.id, ch.device_id, ch.key, ch.label, ch.unit, ch.display_min, ch.display_max, ch.alarm_low, ch.alarm_high,
       ch.enabled AS ch_enabled,
       d.name AS device_name, d.zone, d.poll_interval_s, d.enabled AS d_enabled, d.template_id, d.unit_id,
       c.id AS connection_id, c.name AS connection_name, c.enabled AS c_enabled,
       cl.ts, cl.value, cl.quality, cl.alarm, cl.alarm_since, cl.fault_since, cl.detail,
       ds.state AS dev_state, ds.since AS dev_since, ds.last_ok_ts, ds.last_rtt_ms, ds.last_error
FROM channels ch
JOIN devices d ON d.id = ch.device_id AND d.deleted_at IS NULL
LEFT JOIN connections c ON c.id = d.connection_id
LEFT JOIN channel_latest cl ON cl.channel_id = ch.id
LEFT JOIN device_status ds ON ds.device_id = d.id
ORDER BY d.id, ch.id
"""


def vpd(t: float, rh: float) -> float:
    svp = 0.6108 * math.exp(17.27 * t / (t + 237.3))
    return svp * (1 - rh / 100)


def collector_info(status: dict[str, Any] | None) -> dict[str, Any]:
    if status is None:
        return {"online": False, "waiting": False}
    return {
        "online": True,
        "started_at": status.get("started_at"),
        "last_commit_at": status.get("last_commit_at"),
        # Pi vừa khởi động: collector chưa ghi lần nào thì HMI hiện "Đang chờ dữ liệu".
        "waiting": status.get("last_commit_at") is None,
        "clock_synced": status.get("clock_synced"),
        "clock_warning": status.get("clock_warning"),
        "workers": status.get("workers", []),
    }


def compute(conn: sqlite3.Connection, collector: dict[str, Any] | None, frontend_version: str = "") -> dict[str, Any]:
    now = now_ms()
    s = db.get_settings(conn)
    tdefs = template_defs(conn)
    channels: list[dict[str, Any]] = []
    devices: dict[int, dict[str, Any]] = {}
    for r in conn.execute(_SQL).fetchall():
        tdef = tdefs.get(r["template_id"])
        cdef = next((c for c in tdef.channels if c.key == r["key"]), None) if tdef else None
        if cdef is None:
            continue
        order = tdef.channels.index(cdef) if tdef else 0
        enabled = bool(r["d_enabled"] and r["c_enabled"] and r["ch_enabled"])
        poll_s = r["poll_interval_s"] or 10
        stale_ms = STALE_CYCLES * poll_s * 1000 + 5000
        if not enabled:
            state = "disabled"
        elif r["dev_state"] == "offline":
            state = "offline"
        elif r["quality"] == "sensor_fault":
            state = "fault"
        elif r["ts"] is None:
            state = "nodata"
        elif now - r["ts"] > stale_ms:
            state = "stale"
        elif r["quality"] == "out_of_range":
            state = "out_of_range"
        elif r["alarm"]:
            state = "alarm"
        else:
            state = "ok"
        t_lo, t_hi = cdef.effective_display()
        channels.append(
            {
                "id": r["id"],
                "device_id": r["device_id"],
                "device_name": r["device_name"],
                "connection_name": r["connection_name"],
                "zone": r["zone"],
                "key": r["key"],
                "label": r["label"],
                "unit": r["unit"],
                "decimals": cdef.effective_decimals(),
                "estimate": cdef.estimate,
                "note": cdef.note,
                "order": order,
                "display_min": r["display_min"] if r["display_min"] is not None else t_lo,
                "display_max": r["display_max"] if r["display_max"] is not None else t_hi,
                "valid_min": cdef.min,
                "valid_max": cdef.max,
                "alarm_low": r["alarm_low"],
                "alarm_high": r["alarm_high"],
                "poll_s": poll_s,
                "value": r["value"],
                "ts": r["ts"],
                "quality": r["quality"],
                "state": state,
                "alarm": r["alarm"] if state == "alarm" else None,
                "alarm_since": r["alarm_since"] if state == "alarm" else None,
                "fault_since": r["fault_since"],
                "detail": r["detail"],
                "offline_since": r["dev_since"] if state == "offline" else None,
            }
        )
        if r["device_id"] not in devices:
            if not bool(r["d_enabled"] and r["c_enabled"]):
                dstate = "disabled"
            elif r["dev_state"] == "offline":
                dstate = "offline"
            elif r["last_ok_ts"] is None:
                dstate = "unknown"
            elif now - r["last_ok_ts"] > stale_ms:
                dstate = "stale"
            else:
                dstate = "online"
            devices[r["device_id"]] = {
                "id": r["device_id"],
                "name": r["device_name"],
                "zone": r["zone"],
                "connection_id": r["connection_id"],
                "connection_name": r["connection_name"],
                "unit_id": r["unit_id"],
                "poll_s": poll_s,
                "state": dstate,
                "since": r["dev_since"],
                "rtt_ms": r["last_rtt_ms"],
                "last_ok_at": r["last_ok_ts"],
                "last_error": r["last_error"],
            }
    channels.sort(key=lambda c: (c["device_id"], c["order"]))

    zone_names = sorted({c["zone"] for c in channels}, key=lambda z: (z == "", z))
    zones = []
    for name in zone_names:
        chs = [c for c in channels if c["zone"] == name]
        zones.append(
            {
                "name": name or "Chưa đặt khu vực",
                "channels": [c["id"] for c in chs],
                "devices": list(dict.fromkeys(c["device_id"] for c in chs)),
                "connections": list(dict.fromkeys(c["connection_name"] for c in chs if c["connection_name"])),
            }
        )

    # VPD từ nhiệt độ và độ ẩm của cùng một thiết bị, tính lúc truy vấn, không lưu (spec mục 7).
    derived = []
    for did in devices:
        chs = [c for c in channels if c["device_id"] == did]
        t = next((c for c in chs if c["key"] == "temperature"), None)
        h = next((c for c in chs if c["key"] == "humidity"), None)
        if t is None or h is None:
            continue
        good = {"ok", "alarm"}
        usable = t["value"] is not None and h["value"] is not None and t["state"] in good and h["state"] in good
        derived.append(
            {
                "id": f"vpd:{did}",
                "kind": "vpd",
                "key": "vpd",
                "label": "VPD",
                "unit": "kPa",
                "zone": t["zone"],
                "device_id": did,
                "device_name": t["device_name"],
                "decimals": 2,
                "inputs": [t["id"], h["id"]],
                "value": round(vpd(t["value"], h["value"]), 3) if usable else None,
                "ts": min(t["ts"] or 0, h["ts"] or 0) or None,
                "state": "ok" if usable else ("stale" if "stale" in (t["state"], h["state"]) else "nodata"),
                "display_min": VPD_SCALE[0],
                "display_max": VPD_SCALE[1],
                "alarm_low": None,
                "alarm_high": None,
                "poll_s": t["poll_s"],
                "estimate": False,
                "note": "Tính từ nhiệt độ, độ ẩm",
            }
        )

    alarms = [
        {
            "channel_id": c["id"],
            "label": c["label"],
            "zone": c["zone"],
            "device_name": c["device_name"],
            "value": c["value"],
            "unit": c["unit"],
            "decimals": c["decimals"],
            "kind": c["alarm"],
            "threshold": c["alarm_high"] if c["alarm"] == "high" else c["alarm_low"],
            "since": c["alarm_since"],
            # Kênh ước tính (MQ135): cảnh báo chỉ để tham khảo (spec mục 4.4).
            "advisory": c["estimate"],
        }
        for c in channels
        if c["state"] == "alarm"
    ]

    return {
        "now": now,
        "site_name": s["site_name"],
        "timezone": s["timezone"],
        "frontend_version": frontend_version,
        "collector": collector_info(collector),
        "zones": zones,
        "channels": channels,
        "derived": derived,
        "devices": list(devices.values()),
        "alarms": alarms,
    }

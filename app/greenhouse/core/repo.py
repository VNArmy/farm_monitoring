"""Truy vấn cấu hình dùng chung cho collector và web."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .decode import Block, plan_blocks
from .models import ChannelDef, RtuParams, TcpParams, TemplateDef, parse_params


def template_def(conn: sqlite3.Connection, template_id: int) -> TemplateDef | None:
    r = conn.execute("SELECT name, category, definition FROM device_templates WHERE id = ?", (template_id,)).fetchone()
    if r is None:
        return None
    return TemplateDef(name=r["name"], category=r["category"], **json.loads(r["definition"]))


def template_defs(conn: sqlite3.Connection) -> dict[int, TemplateDef]:
    out = {}
    for r in conn.execute("SELECT id, name, category, definition FROM device_templates"):
        out[r["id"]] = TemplateDef(name=r["name"], category=r["category"], **json.loads(r["definition"]))
    return out


def sync_device_channels(conn: sqlite3.Connection, device_id: int, tdef: TemplateDef) -> None:
    """Sinh kênh từ mẫu: thêm kênh mới (nhãn, đơn vị lấy từ mẫu); đơn vị luôn theo mẫu vì cách giải mã theo mẫu."""
    for c in tdef.channels:
        conn.execute(
            "INSERT INTO channels(device_id, key, label, unit) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(device_id, key) DO UPDATE SET unit = excluded.unit",
            (device_id, c.key, c.label, c.unit),
        )


@dataclass
class RuntimeChannel:
    id: int
    key: str
    label: str
    cdef: ChannelDef
    alarm_low: float | None
    alarm_high: float | None

    # plan_blocks dùng fc, address, type
    @property
    def fc(self) -> int:
        return self.cdef.fc

    @property
    def address(self) -> int:
        return self.cdef.address

    @property
    def type(self) -> str:
        return self.cdef.type


@dataclass
class RuntimeDevice:
    id: int
    name: str
    unit_id: int
    poll_s: int
    channels: list[RuntimeChannel]
    blocks: list[Block] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.blocks = plan_blocks(self.channels)


@dataclass
class RuntimeConnection:
    id: int
    name: str
    type: str
    params: RtuParams | TcpParams
    devices: list[RuntimeDevice]

    @property
    def signature(self) -> str:
        """Tham số buộc phải mở lại cổng khi đổi."""
        return json.dumps([self.type, self.params.model_dump()], sort_keys=True)


def load_runtime(conn: sqlite3.Connection) -> dict[int, RuntimeConnection]:
    tdefs = template_defs(conn)
    chans: dict[int, list[dict[str, Any]]] = {}
    for r in conn.execute("SELECT * FROM channels WHERE enabled = 1 ORDER BY id"):
        chans.setdefault(r["device_id"], []).append(dict(r))
    devices: dict[int, list[RuntimeDevice]] = {}
    for d in conn.execute("SELECT * FROM devices WHERE deleted_at IS NULL AND enabled = 1 ORDER BY id").fetchall():
        tdef = tdefs.get(d["template_id"])
        if tdef is None:
            continue
        by_key = {c.key: c for c in tdef.channels}
        rcs = [
            RuntimeChannel(c["id"], c["key"], c["label"], by_key[c["key"]], c["alarm_low"], c["alarm_high"])
            for c in chans.get(d["id"], [])
            if c["key"] in by_key
        ]
        if rcs:
            devices.setdefault(d["connection_id"], []).append(
                RuntimeDevice(d["id"], d["name"], d["unit_id"], max(1, d["poll_interval_s"]), rcs)
            )
    out = {}
    for c in conn.execute("SELECT * FROM connections WHERE enabled = 1 ORDER BY id"):
        out[c["id"]] = RuntimeConnection(
            c["id"], c["name"], c["type"], parse_params(c["type"], json.loads(c["params"])), devices.get(c["id"], [])
        )
    return out

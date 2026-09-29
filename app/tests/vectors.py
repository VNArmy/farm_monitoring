"""Frame phản hồi thật của Node 01, 02, 03 (PLAN.md, mục Kiểm thử); CRC đã kiểm lại."""

from __future__ import annotations

import json
import struct

from greenhouse.core import config
from greenhouse.core.models import ChannelDef, TemplateDef
from greenhouse.sim.nodes import check_crc

NODE02 = "02 04 0C 42 07 33 33 42 8E CC CD 47 15 38 00 45 76"  # 33,8 °C · 71,4 %RH · 38.200 lux
NODE01_34 = "01 04 02 00 22 39 29"  # raw 34 → 3,4 m/s
NODE02_EXC = "02 83 02 30 F1"  # Exception 02 cho FC 03
NODE01_86 = "01 04 02 00 56 39 0E"  # raw 86 → 8,6 m/s
NODE03 = "03 04 04 44 19 00 00 1D 73"  # 612 ppm, kênh ước tính


def frame(hexstr: str) -> bytes:
    return bytes.fromhex(hexstr.replace(" ", ""))


def registers(hexstr: str) -> list[int]:
    """Tách thanh ghi từ khung phản hồi FC 03/04: unit, fc, số byte, dữ liệu, CRC."""
    f = frame(hexstr)
    assert check_crc(f), "CRC của vector sai"
    n = f[2]
    return list(struct.unpack(f">{n // 2}H", f[3 : 3 + n]))


def templates() -> dict[str, TemplateDef]:
    raw = json.loads((config.seed_dir() / "templates.json").read_text(encoding="utf-8"))
    return {t["name"]: TemplateDef(**t) for t in raw}


def channel(template: str, key: str) -> ChannelDef:
    return next(c for c in templates()[template].channels if c.key == key)

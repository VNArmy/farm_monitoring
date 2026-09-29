"""Giải mã thanh ghi (kiểu, thứ tự byte, hệ số, offset, mã lỗi, NaN, phạm vi hợp lệ) và gộp thanh ghi thành request."""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .models import REG_COUNT, ChannelDef

_FMT = {"int16": ">h", "uint16": ">H", "int32": ">i", "uint32": ">I", "float32": ">f"}

# Spec mục 5: gộp kênh cùng function code, cách nhau không quá 4 thanh ghi, tối đa 125 thanh ghi (FC 03/04).
MAX_GAP = 4
MAX_REGS = 125


def _reorder(b: bytes, order: str | None) -> bytes:
    """Đưa 4 byte về thứ tự ABCD; phép đổi đối xứng nên dùng được cả hai chiều. Kiểu 16 bit giữ nguyên."""
    if len(b) == 2 or order in (None, "ABCD"):
        return b
    if order == "CDAB":
        return b[2:4] + b[0:2]
    if order == "BADC":
        return bytes((b[1], b[0], b[3], b[2]))
    return b[::-1]  # DCBA


def decode(regs: Sequence[int], dtype: str, order: str | None = "ABCD") -> float:
    n = REG_COUNT[dtype]
    raw = b"".join(struct.pack(">H", r & 0xFFFF) for r in regs[:n])
    return float(struct.unpack(_FMT[dtype], _reorder(raw, order))[0])


def encode(value: float, dtype: str, order: str | None = "ABCD") -> list[int]:
    n = REG_COUNT[dtype]
    v: float | int = value if dtype == "float32" else int(round(value))
    b = _reorder(struct.pack(_FMT[dtype], v), order)
    return [int.from_bytes(b[i : i + 2], "big") for i in range(0, 2 * n, 2)]


@dataclass
class Block:
    fc: int
    start: int
    end: int
    channels: list[Any] = field(default_factory=list)

    @property
    def count(self) -> int:
        return self.end - self.start


def plan_blocks(channels: Sequence[Any]) -> list[Block]:
    """channels: đối tượng có fc, address, type."""
    blocks: list[Block] = []
    for ch in sorted(channels, key=lambda c: (c.fc, c.address)):
        end = ch.address + REG_COUNT[ch.type]
        last = blocks[-1] if blocks else None
        if (
            last is not None
            and last.fc == ch.fc
            and ch.address <= last.end + MAX_GAP
            and max(last.end, end) - last.start <= MAX_REGS
        ):
            last.end = max(last.end, end)
            last.channels.append(ch)
        else:
            blocks.append(Block(ch.fc, ch.address, end, [ch]))
    return blocks


@dataclass
class Decoded:
    raw: float | None
    value: float | None
    quality: str  # good | out_of_range | sensor_fault
    detail: str | None = None


def evaluate(ch: ChannelDef, regs: Sequence[int], block_start: int) -> Decoded:
    off = ch.address - block_start
    raw = decode(regs[off : off + ch.regs], ch.type, ch.byte_order)
    if math.isnan(raw) or math.isinf(raw):
        return Decoded(None, None, "sensor_fault", "Node báo NaN")
    if ch.invalid_value is not None and raw == ch.invalid_value:
        return Decoded(raw, None, "sensor_fault", f"Node báo mã lỗi {int(raw)}")
    value = round(raw * ch.scale + ch.offset, ch.effective_decimals() + 3)
    if (ch.min is not None and value < ch.min) or (ch.max is not None and value > ch.max):
        return Decoded(raw, value, "out_of_range", f"Giá trị {value:g} ngoài phạm vi hợp lệ")
    return Decoded(raw, value, "good")


def alarm_state(value: float, low: float | None, high: float | None) -> str | None:
    if high is not None and value > high:
        return "high"
    if low is not None and value < low:
        return "low"
    return None


def address_hint(address: int, fc: int) -> str | None:
    """Gợi ý quy đổi địa chỉ kiểu datasheet (40001, 30010) sang địa chỉ giao thức."""
    if fc == 3 and 40001 <= address <= 49999:
        return f"{address} theo quy ước 4xxxx là địa chỉ {address - 40001} với FC 03"
    if fc == 4 and 30001 <= address <= 39999:
        return f"{address} theo quy ước 3xxxx là địa chỉ {address - 30001} với FC 04"
    return None

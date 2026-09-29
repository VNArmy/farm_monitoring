"""Mô hình node và bus RS-485 mô phỏng.

Bảng thanh ghi giống node thật (spec mục 4.5):
- Node 01 tốc độ gió: unit ID 1, int16 ở input register 1, hệ số 0,1; lỗi cảm biến trả -32768.
- Node 02 nhiệt độ, độ ẩm, ánh sáng: unit ID 2, float32 ABCD ở input register 0, 2, 4; lỗi trả NaN.
- Node 03 CO2 (MQ135): unit ID 3, float32 ABCD ở input register 0; trả NaN trong lúc làm nóng.
Thêm một cảm biến CO2 mới chưa cấu hình ở ID 1 · 4800 baud để thử quét bus và đổi địa chỉ.
Mọi node có holding register 256 = địa chỉ, 257 = mã baud, ghi bằng FC 06.

Lỗi theo kịch bản cho từng node (plan mục Kiểm thử): silent (im lặng), bad_crc (CRC sai), sensor_fault
(NaN cho float32, -32768 cho int16). Đặt bằng Bus.set_fault() hoặc biến môi trường
GREENHOUSE_SIM_FAULTS="2:silent,3:sensor_fault".
"""

from __future__ import annotations

import math
import os
import random
import struct
import threading
import time

from ..core.decode import encode

ADDR_REGISTER = 256
BAUD_REGISTER = 257
BAUD_CODES = {2400: 0, 4800: 1, 9600: 2, 19200: 3, 38400: 4, 57600: 5, 115200: 6}
CODE_TO_BAUD = {v: k for k, v in BAUD_CODES.items()}
FAULTS = ("silent", "bad_crc", "sensor_fault")

TZ_OFFSET_S = 7 * 3600
settings = {"warmup_s": 45.0, "timeout_rate": 0.003, "crc_rate": 0.001}


def _day_offset(day: int) -> float:
    x = math.sin(day * 12.9898) * 43758.5453
    return (x - math.floor(x)) * 4.0 - 1.0


def physics(ts: float) -> dict[str, float]:
    """Giá trị "thật" trong nhà kính tại thời điểm ts (giây epoch): chu kỳ ngày đêm và dao động nhỏ."""
    local = ts + TZ_OFFSET_S
    h = (local % 86400) / 3600
    day_off = _day_offset(int(local // 86400))
    s = math.sin(2 * math.pi * (h - 9) / 24)
    daylight = max(0.0, math.sin(math.pi * (h - 6) / 12))
    temp = (
        24.5 + 6.2 * s + day_off + 0.35 * math.sin(ts / 1300) + 0.2 * math.sin(ts / 487 + 1) + 0.08 * math.sin(ts / 97)
    )
    rh = 84 - 11 * s - 0.9 * day_off + 0.8 * math.sin(ts / 1700) + 0.4 * math.sin(ts / 611)
    cloud = 0.75 + 0.2 * math.sin(ts / 2900) + 0.05 * math.sin(ts / 233)
    lux = (daylight**1.2) * 62000 * cloud
    co2 = 640 - 190 * daylight + 14 * math.sin(ts / 800) + 7 * math.sin(ts / 211)
    wind = 3 + 1.2 * math.sin(ts / 900) + 0.8 * math.sin(ts / 300 + 2) + 0.5 * math.sin(ts / 77) + 0.6 * daylight
    return {
        "temperature": round(temp, 2),
        "humidity": round(min(99.0, max(25.0, rh)), 2),
        "illuminance": round(max(0.0, lux), 0),
        "co2": round(co2, 1),
        "wind_speed": round(max(0.0, wind), 1),
    }


def _crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def with_crc(frame: bytes) -> bytes:
    c = _crc16(frame)
    return frame + bytes((c & 0xFF, c >> 8))


def check_crc(frame: bytes) -> bool:
    return len(frame) >= 4 and _crc16(frame[:-2]) == (frame[-2] | (frame[-1] << 8))


class Node:
    def __init__(self, kind: str, unit_id: int, baud: int = 9600, parity: str = "N", stopbits: int = 1):
        self.kind = kind
        self.unit_id = unit_id
        self.baud = baud
        self.parity = parity
        self.stopbits = stopbits
        self.started = time.time()
        self.fault: str | None = None
        self.holding = {ADDR_REGISTER: unit_id, BAUD_REGISTER: BAUD_CODES.get(baud, 2)}

    def input_registers(self, now: float) -> dict[int, int]:
        v = physics(now)
        broken = self.fault == "sensor_fault"
        if self.kind == "wind":
            raw = -32768 if broken else int(round(v["wind_speed"] * 10))
            return {0: 0, 1: raw & 0xFFFF, 2: 0, 3: 0}
        if self.kind == "climate":
            regs: list[int] = []
            for key in ("temperature", "humidity", "illuminance"):
                regs += encode(float("nan") if broken else v[key], "float32", "ABCD")
            return dict(enumerate(regs))
        if self.kind == "co2":
            warming = now - self.started < settings["warmup_s"]
            value = float("nan") if broken or warming else v["co2"]
            return dict(enumerate(encode(value, "float32", "ABCD")))
        return {}

    def handle(self, pdu: bytes, now: float) -> tuple[bytes, dict[str, int]]:
        """PDU phản hồi và thay đổi cấu hình cần áp dụng sau khi trả lời."""
        fc = pdu[0]
        if fc in (3, 4) and len(pdu) == 5:
            addr, count = struct.unpack(">HH", pdu[1:5])
            regs = self.input_registers(now) if fc == 4 else self.holding
            if not 1 <= count <= 125 or any(a not in regs for a in range(addr, addr + count)):
                return bytes((fc | 0x80, 2)), {}
            data = b"".join(struct.pack(">H", regs[a] & 0xFFFF) for a in range(addr, addr + count))
            return bytes((fc, len(data))) + data, {}
        if fc == 6 and len(pdu) == 5:
            addr, value = struct.unpack(">HH", pdu[1:5])
            if addr == ADDR_REGISTER:
                return (pdu, {"unit_id": value}) if 1 <= value <= 247 else (bytes((0x86, 3)), {})
            if addr == BAUD_REGISTER:
                return (pdu, {"baud": CODE_TO_BAUD[value]}) if value in CODE_TO_BAUD else (bytes((0x86, 3)), {})
            return bytes((0x86, 2)), {}
        return bytes((fc | 0x80, 1)), {}

    def apply(self, changes: dict[str, int]) -> None:
        if "unit_id" in changes:
            self.unit_id = changes["unit_id"]
            self.holding[ADDR_REGISTER] = self.unit_id
        if "baud" in changes:
            self.baud = changes["baud"]
            self.holding[BAUD_REGISTER] = BAUD_CODES[self.baud]


def corrupt(frame: bytes) -> bytes:
    return frame[:-1] + bytes(((frame[-1] ^ 0x5A) & 0xFF,))


class Bus:
    """Bus RS-485 dùng chung: nhiều node, một request tại một thời điểm."""

    def __init__(self, nodes: list[Node]):
        self.nodes = nodes
        self.lock = threading.Lock()
        self.rng = random.Random()

    def set_fault(self, unit_id: int, fault: str | None, baud: int = 9600) -> None:
        """Đặt kịch bản lỗi cho node ở unit_id trên baud của bus (không đụng cảm biến mới ở 4800)."""
        for n in self.nodes:
            if n.unit_id == unit_id and n.baud == baud:
                n.fault = fault

    def handle_rtu(self, frame: bytes, baud: int, parity: str, stopbits: int) -> tuple[bytes | None, float]:
        with self.lock:
            if not check_crc(frame):
                return None, 0.0
            unit = frame[0]
            nodes = [
                n
                for n in self.nodes
                if n.unit_id == unit and n.baud == baud and n.parity == parity and n.stopbits == stopbits
            ]
            if not nodes or nodes[0].fault == "silent":
                return None, 0.0
            r = self.rng.random()
            if r < settings["timeout_rate"]:
                return None, 0.0
            node = nodes[0]
            resp_pdu, changes = node.handle(frame[1:-2], time.time())
            response = with_crc(bytes((unit,)) + resp_pdu)
            # Hai node trùng địa chỉ cùng trả lời, nhiễu, hoặc kịch bản CRC sai: khung hỏng.
            if len(nodes) > 1 or node.fault == "bad_crc" or r < settings["timeout_rate"] + settings["crc_rate"]:
                response = corrupt(response)
            node.apply(changes)
            char_s = 11 / baud
            latency = 0.02 + self.rng.random() * 0.02 + (len(frame) + len(response)) * char_s
            return response, latency


def default_nodes(with_new_sensor: bool = True) -> list[Node]:
    nodes = [Node("wind", 1), Node("climate", 2), Node("co2", 3)]
    if with_new_sensor:
        nodes.append(Node("co2", 1, baud=4800))
    return nodes


def faults_from_env() -> dict[int, str]:
    out = {}
    for part in os.environ.get("GREENHOUSE_SIM_FAULTS", "").split(","):
        uid, _, fault = part.strip().partition(":")
        if uid.isdigit() and fault in FAULTS:
            out[int(uid)] = fault
    return out


_buses: dict[str, Bus] = {}
_buses_lock = threading.Lock()


def get_bus(name: str) -> Bus:
    with _buses_lock:
        bus = _buses.get(name)
        if bus is None:
            bus = Bus(default_nodes())
            for uid, fault in faults_from_env().items():
                bus.set_fault(uid, fault)
            _buses[name] = bus
        return bus


def reset_buses() -> None:
    with _buses_lock:
        _buses.clear()

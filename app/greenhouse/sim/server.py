"""Simulator Modbus TCP bằng server pymodbus: Node 01, 02, 03 với cùng bảng thanh ghi như node thật.

framing "tcp": Modbus TCP (thiết bị TCP gốc hoặc gateway chế độ Modbus gateway);
framing "rtu": RTU over TCP (gateway truyền trong suốt).
Lỗi theo kịch bản: silent (không trả lời), bad_crc (khung hỏng), sensor_fault (NaN, -32768).
"""

from __future__ import annotations

import logging
import time
from functools import partial

from pymodbus.constants import ExcCodes
from pymodbus.framer import FramerType
from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice

from .nodes import ADDR_REGISTER, BAUD_REGISTER, Node, corrupt, default_nodes

log = logging.getLogger("greenhouse.sim")


async def _action(
    node: Node,
    fc: int,
    start: int,
    address: int,
    count: int,
    regs: list[int],
    set_values: list[int] | list[bool] | None,
) -> ExcCodes | None:
    if fc == 4:
        values = node.input_registers(time.time())
        if any(a not in values for a in range(address, address + count)):
            return ExcCodes.ILLEGAL_ADDRESS
        for i in range(len(regs)):
            regs[i] = values.get(start + i, 0) & 0xFFFF
        return None
    if any(a not in node.holding for a in range(address, address + count)):
        return ExcCodes.ILLEGAL_ADDRESS
    for i in range(len(regs)):
        regs[i] = node.holding.get(start + i, 0)
    return None


def build_devices(nodes: list[Node]) -> list[SimDevice]:
    devices = []
    for n in nodes:
        size = max(n.input_registers(time.time())) + 1
        devices.append(
            SimDevice(
                id=n.unit_id,
                simdata=(
                    [SimData(0, count=16, values=False, datatype=DataType.BITS)],
                    [SimData(0, count=16, values=False, datatype=DataType.BITS)],
                    [
                        SimData(
                            ADDR_REGISTER,
                            count=BAUD_REGISTER - ADDR_REGISTER + 1,
                            values=0,
                            datatype=DataType.REGISTERS,
                        )
                    ],
                    [SimData(0, count=size, values=0, datatype=DataType.REGISTERS)],
                ),
                action=partial(_action, n),
            )
        )
    return devices


def make_trace(nodes: list[Node], framing: str):
    by_id = {n.unit_id: n for n in nodes}

    def trace(sending: bool, data: bytes) -> bytes:
        if not sending or not data:
            return data
        unit = data[6] if framing == "tcp" and len(data) > 6 else data[0]
        node = by_id.get(unit)
        if node is None:
            return b""  # unit ID không có trên bus: im lặng như bus thật
        if node.fault is None:
            return data
        if node.fault == "silent":
            return b""
        if node.fault == "bad_crc":
            return corrupt(data) if framing == "rtu" else data[:-1]
        return data

    return trace


async def run_tcp(host: str, port: int, framing: str = "tcp", faults: dict[int, str] | None = None) -> None:
    nodes = default_nodes(with_new_sensor=False)
    for uid, fault in (faults or {}).items():
        for n in nodes:
            if n.unit_id == uid:
                n.fault = fault
    server = ModbusTcpServer(
        build_devices(nodes),
        framer=FramerType.SOCKET if framing == "tcp" else FramerType.RTU,
        address=(host, port),
        ignore_missing_devices=True,
        trace_packet=make_trace(nodes, framing),
    )
    log.info("Simulator Modbus %s ở %s:%d", "TCP" if framing == "tcp" else "RTU over TCP", host, port)
    await server.serve_forever()

"""Client Modbus (pymodbus 3.15) với frame thật phát lại qua cổng ảo sim://, và với simulator Modbus TCP."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from conftest import free_port
from vectors import NODE01_34, NODE01_86, NODE02, NODE02_EXC, NODE03, channel, frame

from greenhouse.collector.bus import BusClient, BusError
from greenhouse.core.decode import evaluate
from greenhouse.core.models import RtuParams, TcpParams
from greenhouse.sim import nodes
from greenhouse.sim.nodes import check_crc, corrupt
from greenhouse.sim.server import run_tcp


class ReplayBus:
    """Bus trả đúng một khung đã ghi lại (hoặc im lặng), ghi nhận các request nhận được."""

    def __init__(self, response: bytes | None):
        self.response = response
        self.requests: list[bytes] = []

    def handle_rtu(self, request: bytes, baud: int, parity: str, stopbits: int) -> tuple[bytes | None, float]:
        self.requests.append(request)
        return self.response, 0.005


def replay(name: str, response: bytes | None) -> ReplayBus:
    bus = ReplayBus(response)
    nodes._buses[name] = bus  # type: ignore[assignment]
    return bus


def rtu(name: str, **over: object) -> RtuParams:
    return RtuParams(**{"port": f"sim://{name}", "timeout_ms": 200, "retries": 0, "gap_ms": 0, **over})  # type: ignore[arg-type]


async def test_replay_node02_frame() -> None:
    bus = replay("v02", frame(NODE02))
    client = BusClient("rtu", rtu("v02"))
    try:
        rr = await client.read(2, 4, 0, 6)
    finally:
        client.close()
    assert rr.regs == [0x4207, 0x3333, 0x428E, 0xCCCD, 0x4715, 0x3800]
    assert rr.rx == frame(NODE02)
    assert rr.tx[:6] == bytes([2, 4, 0, 0, 0, 6]) and check_crc(rr.tx)
    assert bus.requests == [rr.tx]
    assert rr.data_offset == 3
    temp = channel("Node nhiệt ẩm, ánh sáng", "temperature")
    assert evaluate(temp, rr.regs, 0).value == 33.8


@pytest.mark.parametrize(("hexstr", "value"), [(NODE01_34, 3.4), (NODE01_86, 8.6)])
async def test_replay_node01_frames(hexstr: str, value: float) -> None:
    replay("v01", frame(hexstr))
    client = BusClient("rtu", rtu("v01"))
    try:
        rr = await client.read(1, 4, 1, 1)
    finally:
        client.close()
    assert evaluate(channel("Node tốc độ gió", "wind_speed"), rr.regs, 1).value == value


async def test_replay_node03_frame() -> None:
    replay("v03", frame(NODE03))
    client = BusClient("rtu", rtu("v03"))
    try:
        rr = await client.read(3, 4, 0, 2)
    finally:
        client.close()
    assert evaluate(channel("Node CO2 (MQ135)", "co2"), rr.regs, 0).value == 612


async def test_replay_exception_02() -> None:
    replay("vexc", frame(NODE02_EXC))
    client = BusClient("rtu", rtu("vexc", retries=2))
    with pytest.raises(BusError) as e:
        await client.read(2, 3, 0, 6)
    client.close()
    assert e.value.kind == "exception"
    assert e.value.code == 2
    assert e.value.name == "Illegal Data Address"
    assert e.value.rx == frame(NODE02_EXC)


async def test_timeout_retries_then_fails() -> None:
    bus = replay("vsilent", None)
    client = BusClient("rtu", rtu("vsilent", retries=1, timeout_ms=100))
    with pytest.raises(BusError) as e:
        await client.read(2, 4, 0, 6)
    client.close()
    assert e.value.kind == "timeout"
    assert len(bus.requests) == 2  # lần đầu và một lần thử lại


async def test_bad_crc_is_not_a_timeout() -> None:
    replay("vcrc", corrupt(frame(NODE02)))
    client = BusClient("rtu", rtu("vcrc"))
    with pytest.raises(BusError) as e:
        await client.read(2, 4, 0, 6)
    client.close()
    assert e.value.kind == "crc"
    assert e.value.rx  # vẫn giữ byte nhận được để hiện trên log frame


async def test_frame_hook_sees_tx_and_rx() -> None:
    replay("vhook", frame(NODE03))
    seen: list[tuple[str, str, str | None]] = []
    client = BusClient("rtu", rtu("vhook"), on_frame=lambda d, b, n: seen.append((d, b.hex(" ").upper(), n)))
    await client.read(3, 4, 0, 2)
    client.close()
    assert [s[0] for s in seen] == ["TX", "RX"]
    assert seen[1][1] == NODE03


async def test_simulated_bus_and_address_change() -> None:
    """Bus mô phỏng: ID 1–3 ở 9600, cảm biến CO2 mới ở ID 1 · 4800; đổi địa chỉ bằng FC 06."""
    client = BusClient("rtu", rtu("addr"))
    try:
        assert (await client.read(2, 4, 0, 6)).regs
        with pytest.raises(BusError) as e:
            await client.read(9, 4, 0, 1)
        assert e.value.kind == "timeout"
    finally:
        client.close()
    slow = BusClient("rtu", rtu("addr"), baudrate=4800)
    try:
        await slow.read(1, 4, 0, 2)
        await slow.write_register(1, nodes.ADDR_REGISTER, 7)
        assert (await slow.read(7, 3, nodes.ADDR_REGISTER, 1)).regs == [7]
    finally:
        slow.close()


# --- Simulator Modbus TCP (pymodbus server) -------------------------------------------------


@pytest.fixture
async def tcp_sim(request: pytest.FixtureRequest) -> AsyncIterator[int]:
    framing, faults = getattr(request, "param", ("tcp", {}))
    port = free_port()
    task = asyncio.create_task(run_tcp("127.0.0.1", port, framing, faults))
    for _ in range(100):
        try:
            _, w = await asyncio.open_connection("127.0.0.1", port)
            w.close()
            break
        except OSError:
            await asyncio.sleep(0.05)
    yield port
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_tcp_simulator_values(tcp_sim: int) -> None:
    client = BusClient("tcp", TcpParams(host="127.0.0.1", port=tcp_sim, timeout_ms=500, retries=0))
    try:
        rr = await client.read(2, 4, 0, 6)
        assert rr.data_offset == 9
        temp = evaluate(channel("Node nhiệt ẩm, ánh sáng", "temperature"), rr.regs, 0)
        assert temp.quality == "good" and 5 < (temp.value or 0) < 45
        wind = await client.read(1, 4, 1, 1)
        assert evaluate(channel("Node tốc độ gió", "wind_speed"), wind.regs, 1).quality == "good"
        with pytest.raises(BusError) as e:
            await client.read(2, 4, 40, 2)
        assert (e.value.kind, e.value.code) == ("exception", 2)
        with pytest.raises(BusError) as e:
            await client.read(9, 4, 0, 1)
        assert e.value.kind == "timeout"
    finally:
        client.close()


@pytest.mark.parametrize("tcp_sim", [("rtu", {2: "bad_crc", 3: "silent"})], indirect=True)
async def test_rtu_over_tcp_faults(tcp_sim: int) -> None:
    client = BusClient(
        "tcp", TcpParams(host="127.0.0.1", port=tcp_sim, framing="rtu_over_tcp", timeout_ms=300, retries=0)
    )
    try:
        assert (await client.read(1, 4, 1, 1)).data_offset == 3
        with pytest.raises(BusError) as e:
            await client.read(2, 4, 0, 6)
        assert e.value.kind == "crc"
        with pytest.raises(BusError) as e:
            await client.read(3, 4, 0, 2)
        assert e.value.kind == "timeout"
    finally:
        client.close()

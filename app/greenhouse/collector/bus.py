"""Client Modbus cho một kết nối, bọc pymodbus async: thử lại theo cấu hình, nghỉ giữa request, phân loại lỗi,
giữ khung TX/RX thô cho Đọc thử và log frame."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusException, ModbusIOException
from pymodbus.framer import FramerType

from ..core.models import RtuParams, TcpParams

logging.getLogger("pymodbus").setLevel(logging.CRITICAL)

EXCEPTION_NAMES = {
    1: "Illegal Function",
    2: "Illegal Data Address",
    3: "Illegal Data Value",
    4: "Slave Device Failure",
    5: "Acknowledge",
    6: "Slave Device Busy",
    8: "Memory Parity Error",
    10: "Gateway Path Unavailable",
    11: "Gateway Target Device Failed to Respond",
}

# on_frame(hướng "TX"/"RX", byte, ghi chú)
FrameHook = Callable[[str, bytes, "str | None"], None]


class BusError(Exception):
    """kind: timeout | crc | exception | io."""

    def __init__(self, kind: str, message: str, code: int | None = None, tx: bytes = b"", rx: bytes = b""):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.code = code
        self.tx = tx
        self.rx = rx

    @property
    def name(self) -> str | None:
        return EXCEPTION_NAMES.get(self.code or 0) if self.kind == "exception" else None


@dataclass
class ReadResult:
    regs: list[int]
    tx: bytes
    rx: bytes
    rtt_ms: float
    data_offset: int  # vị trí byte dữ liệu thanh ghi đầu tiên trong rx


class BusClient:
    def __init__(
        self,
        conn_type: str,
        params: RtuParams | TcpParams,
        *,
        baudrate: int | None = None,
        timeout_ms: int | None = None,
        on_frame: FrameHook | None = None,
    ):
        self.conn_type = conn_type
        self.params = params
        self.baudrate = baudrate or (params.baudrate if isinstance(params, RtuParams) else None)
        self.timeout_s = (timeout_ms or params.timeout_ms) / 1000
        self.retries = params.retries
        self.gap_s = params.gap_ms / 1000
        self.on_frame = on_frame
        self._client: AsyncModbusSerialClient | AsyncModbusTcpClient | None = None
        self._tx = b""
        self._rx = b""
        self._last_end = 0.0

    @property
    def data_offset(self) -> int:
        if isinstance(self.params, TcpParams) and self.params.framing == "tcp":
            return 9  # MBAP 7 byte, function code, byte count
        return 3  # unit ID, function code, byte count

    @property
    def target(self) -> str:
        if isinstance(self.params, RtuParams):
            return f"{self.params.port} ({self.baudrate} 8{self.params.parity}{self.params.stopbits})"
        return f"{self.params.host}:{self.params.port}"

    def _trace(self, sending: bool, data: bytes) -> bytes:
        if sending:
            self._tx = bytes(data)
        else:
            self._rx = bytes(data)
        return data

    def _make(self) -> AsyncModbusSerialClient | AsyncModbusTcpClient:
        p = self.params
        if isinstance(p, RtuParams):
            return AsyncModbusSerialClient(
                p.port,
                framer=FramerType.RTU,
                baudrate=self.baudrate or p.baudrate,
                bytesize=8,
                parity=p.parity,
                stopbits=p.stopbits,
                timeout=self.timeout_s,
                retries=0,
                reconnect_delay=0,
                trace_packet=self._trace,
            )
        return AsyncModbusTcpClient(
            p.host,
            port=p.port,
            framer=FramerType.SOCKET if p.framing == "tcp" else FramerType.RTU,
            timeout=self.timeout_s,
            retries=0,
            reconnect_delay=0,
            trace_packet=self._trace,
        )

    async def open(self) -> None:
        if self._client is not None and self._client.connected:
            return
        self.close()
        client = self._make()
        # Tự quản lý việc mở lại cổng; không để pymodbus tự đóng sau vài lần không phản hồi.
        client.set_max_no_responses(1_000_000)
        try:
            ok = await client.connect()
        except Exception as e:
            client.close()
            raise BusError("io", f"Không mở được {self.target}: {e}") from e
        if not ok:
            client.close()
            raise BusError("io", f"Không mở được {self.target} sau {int(self.timeout_s * 1000)} ms")
        self._client = client

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def _emit(self, err: BusError | None) -> None:
        if self.on_frame is None:
            return
        try:
            if self._tx:
                self.on_frame("TX", self._tx, None)
            if self._rx:
                self.on_frame("RX", self._rx, err.message if err else None)
            elif err is not None:
                self.on_frame("RX", b"", err.message)
        except Exception:
            pass

    async def _call(self, fn: Callable[[Any], Awaitable[Any]], retries: int | None) -> tuple[Any, float]:
        attempts = 1 + (self.retries if retries is None else retries)
        last: BusError | None = None
        for _ in range(attempts):
            wait = self._last_end + self.gap_s - time.perf_counter()
            if wait > 0:
                await asyncio.sleep(wait)
            await self.open()
            assert self._client is not None
            self._tx = self._rx = b""
            started = time.perf_counter()
            try:
                pdu = await fn(self._client)
            except ModbusIOException as e:
                if "device id" in str(e):
                    last = BusError("crc", "Phản hồi từ unit ID khác", tx=self._tx, rx=self._rx)
                elif self._rx:
                    last = BusError("crc", "Khung trả lời hỏng (sai CRC hoặc sai định dạng)", tx=self._tx, rx=self._rx)
                else:
                    last = BusError("timeout", "Không phản hồi", tx=self._tx, rx=self._rx)
                self._emit(last)
                continue
            except (ConnectionException, OSError) as e:
                self.close()
                last = BusError("io", f"Mất kết nối {self.target}: {e}", tx=self._tx, rx=self._rx)
                self._emit(last)
                continue
            except ModbusException as e:
                last = BusError("crc", f"Phản hồi không hợp lệ: {e}", tx=self._tx, rx=self._rx)
                self._emit(last)
                continue
            finally:
                self._last_end = time.perf_counter()
            rtt = (time.perf_counter() - started) * 1000
            if pdu.isError():
                code = int(getattr(pdu, "exception_code", 0))
                err = BusError(
                    "exception",
                    f"Exception {code:02d} · {EXCEPTION_NAMES.get(code, 'Unknown')}",
                    code,
                    self._tx,
                    self._rx,
                )
                self._emit(err)
                raise err
            self._emit(None)
            return pdu, rtt
        assert last is not None
        raise last

    async def read(self, unit: int, fc: int, address: int, count: int, retries: int | None = None) -> ReadResult:
        def call(c: Any) -> Awaitable[Any]:
            fn = c.read_input_registers if fc == 4 else c.read_holding_registers
            return fn(address, count=count, device_id=unit)

        pdu, rtt = await self._call(call, retries)
        regs = list(pdu.registers or [])
        if len(regs) != count:
            raise BusError("crc", f"Trả về {len(regs)} thanh ghi, cần {count}", tx=self._tx, rx=self._rx)
        return ReadResult(regs, self._tx, self._rx, rtt, self.data_offset)

    async def write_register(self, unit: int, address: int, value: int, retries: int = 0) -> float:
        def call(c: Any) -> Awaitable[Any]:
            return c.write_register(address, value & 0xFFFF, device_id=unit)

        _, rtt = await self._call(call, retries)
        return rtt

"""Handler pyserial cho URL sim://<tên>: cổng serial ảo nối vào bus mô phỏng trong cùng process.

pyserial tìm module protocol_<scheme> trong serial.protocol_handler_packages; gói greenhouse.sim tự đăng ký.
"""

from __future__ import annotations

import time
import urllib.parse

from serial.serialutil import PortNotOpenError, SerialBase, SerialException

from .nodes import get_bus


def _force_poll() -> None:
    # Cổng ảo không có file descriptor để asyncio theo dõi, nên transport của pymodbus phải thăm dò.
    try:
        from pymodbus.transport.serialtransport import SerialTransport

        SerialTransport.force_poll = True
    except ImportError:
        pass


class Serial(SerialBase):
    def open(self) -> None:
        if self._port is None:
            raise SerialException("Chưa đặt cổng")
        if self.is_open:
            raise SerialException("Cổng đã mở")
        self._name = self.from_url(self._port)
        self._bus = get_bus(self._name)
        self._buf = b""
        self._ready_at = float("inf")
        self.is_open: bool = True
        _force_poll()

    def from_url(self, url: str) -> str:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "sim":
            raise SerialException(f"URL không phải sim://: {url}")
        return parts.netloc or parts.path or "demo"

    def _reconfigure_port(self, force_update: bool = False) -> None:
        pass

    def close(self) -> None:
        self.is_open = False

    @property
    def in_waiting(self) -> int:
        if not self.is_open:
            raise PortNotOpenError()
        return len(self._buf) if time.monotonic() >= self._ready_at else 0

    def read(self, size: int = 1) -> bytes:
        if not self.is_open:
            raise PortNotOpenError()
        deadline = time.monotonic() + (self._timeout or 0)
        while time.monotonic() < self._ready_at and time.monotonic() < deadline:
            time.sleep(0.001)
        if time.monotonic() < self._ready_at:
            return b""
        out, self._buf = self._buf[:size], self._buf[size:]
        return bytes(out)

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise PortNotOpenError()
        response, latency = self._bus.handle_rtu(bytes(data), self._baudrate, self._parity, int(self._stopbits))
        if response:
            self._buf = response
            self._ready_at = time.monotonic() + latency
        else:
            self._buf = b""
            self._ready_at = float("inf")
        return len(data)

    def reset_input_buffer(self) -> None:
        self._buf = b""

    def reset_output_buffer(self) -> None:
        pass

    def flush(self) -> None:
        pass

    def _update_rts_state(self) -> None:
        pass

    def _update_dtr_state(self) -> None:
        pass

    @property
    def cts(self) -> bool:
        return False

    @property
    def dsr(self) -> bool:
        return False

    @property
    def ri(self) -> bool:
        return False

    @property
    def cd(self) -> bool:
        return False

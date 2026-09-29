"""Model cấu hình dùng chung: tham số kết nối, mẫu thiết bị (định dạng JSON ở spec mục 4.4), thiết bị."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .errors import invalid

BAUDRATES = (2400, 4800, 9600, 19200, 38400, 57600, 115200)
DTYPES = ("int16", "uint16", "int32", "uint32", "float32")
REG_COUNT = {"int16": 1, "uint16": 1, "int32": 2, "uint32": 2, "float32": 2}
BYTE_ORDERS = ("ABCD", "CDAB", "BADC", "DCBA")
CATEGORIES = ("climate", "wind", "light", "co2", "nutrient", "other")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

Baud = Literal[2400, 4800, 9600, 19200, 38400, 57600, 115200]

# --- Kết nối -------------------------------------------------------------------------------


class RtuParams(BaseModel):
    model_config = ConfigDict(extra="ignore")
    port: str = Field(min_length=1, max_length=255)
    baudrate: Baud = 9600
    parity: Literal["N", "E", "O"] = "N"
    stopbits: Literal[1, 2] = 1
    timeout_ms: int = Field(500, ge=50, le=10000)
    retries: int = Field(1, ge=0, le=3)
    gap_ms: int = Field(20, ge=0, le=2000)


class TcpParams(BaseModel):
    model_config = ConfigDict(extra="ignore")
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(502, ge=1, le=65535)
    framing: Literal["tcp", "rtu_over_tcp"] = "tcp"
    timeout_ms: int = Field(1000, ge=50, le=10000)
    retries: int = Field(1, ge=0, le=3)
    gap_ms: int = Field(0, ge=0, le=2000)


def parse_params(conn_type: str, params: dict[str, Any]) -> RtuParams | TcpParams:
    return RtuParams(**params) if conn_type == "rtu" else TcpParams(**params)


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    type: Literal["rtu", "tcp"]
    params: dict[str, Any]
    enabled: bool = True

    def typed_params(self) -> RtuParams | TcpParams:
        return parse_params(self.type, self.params)


# --- Mẫu thiết bị --------------------------------------------------------------------------


class ChannelDef(BaseModel):
    """Một kênh của mẫu. Tên trường theo định dạng JSON import/export của spec."""

    model_config = ConfigDict(extra="ignore")
    key: str
    label: str = Field(min_length=1, max_length=40)
    unit: str = Field("", max_length=16)
    fc: Literal[3, 4] = 4
    address: int = Field(ge=0, le=65535)
    type: Literal["int16", "uint16", "int32", "uint32", "float32"] = "float32"
    byte_order: Literal["ABCD", "CDAB", "BADC", "DCBA"] | None = None
    scale: float = 1
    offset: float = 0
    min: float | None = None
    max: float | None = None
    display_min: float | None = None
    display_max: float | None = None
    invalid_value: int | None = None
    agg: Literal["mean", "circular_mean"] = "mean"
    decimals: int | None = Field(None, ge=0, le=3)
    estimate: bool = False
    note: str = Field("", max_length=60)

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not KEY_RE.match(v):
            raise ValueError("chỉ gồm chữ thường, số, gạch dưới, bắt đầu bằng chữ")
        return v

    @property
    def regs(self) -> int:
        return REG_COUNT[self.type]

    @property
    def is32(self) -> bool:
        return self.regs == 2

    def effective_decimals(self) -> int:
        if self.decimals is not None:
            return self.decimals
        if self.unit in ("lux", "ppm") or (self.type != "float32" and self.scale == 1):
            return 0
        return 1

    def effective_display(self) -> tuple[float | None, float | None]:
        """Thang hiển thị mặc định; bỏ trống thì dùng phạm vi hợp lệ."""
        lo = self.display_min if self.display_min is not None else self.min
        hi = self.display_max if self.display_max is not None else self.max
        return lo, hi


class TemplateDef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=1, max_length=60)
    category: str = "other"
    address_register: int | None = Field(None, ge=0, le=65535)
    baud_register: int | None = Field(None, ge=0, le=65535)
    baud_codes: dict[str, int] | None = None
    channels: list[ChannelDef] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def _normalize(self) -> TemplateDef:
        for ch in self.channels:
            if not ch.is32:
                ch.byte_order = None
        return self

    def definition(self) -> dict[str, Any]:
        """Phần lưu vào cột device_templates.definition."""
        d = self.model_dump(exclude={"name", "category"}, exclude_none=False)
        return d


def validate_template(t: TemplateDef) -> None:
    """Các kiểm tra form mẫu ở spec mục 8.3; lỗi chỉ đúng ô (field = channels.<i>.<trường>)."""
    if t.category not in CATEGORIES:
        raise invalid("Nhóm không hợp lệ", "category")
    seen: dict[str, int] = {}
    for i, c in enumerate(t.channels):
        f = f"channels.{i}"
        if c.key in seen:
            raise invalid(f"Key “{c.key}” bị trùng với kênh {seen[c.key] + 1}", f"{f}.key")
        seen[c.key] = i
        if c.is32 and c.byte_order is None:
            raise invalid("Kiểu 32 bit cần chọn thứ tự byte", f"{f}.byte_order")
        if c.scale == 0:
            raise invalid("Hệ số phải khác 0", f"{f}.scale")
        if c.address + c.regs > 65536:
            raise invalid("Địa chỉ vượt quá 65535", f"{f}.address")
        if c.min is not None and c.max is not None and c.min >= c.max:
            raise invalid("Phạm vi hợp lệ: “từ” phải nhỏ hơn “đến”", f"{f}.max")
        if c.display_min is not None and c.display_max is not None and c.display_min >= c.display_max:
            raise invalid("Thang hiển thị: “từ” phải nhỏ hơn “đến”", f"{f}.display_max")
        if c.display_min is not None and c.min is not None and c.display_min < c.min:
            raise invalid("Thang hiển thị phải nằm trong phạm vi hợp lệ", f"{f}.display_min")
        if c.display_max is not None and c.max is not None and c.display_max > c.max:
            raise invalid("Thang hiển thị phải nằm trong phạm vi hợp lệ", f"{f}.display_max")
    items = sorted(enumerate(t.channels), key=lambda x: (x[1].fc, x[1].address))
    for n, (_, a) in enumerate(items):
        for j, b in items[n + 1 :]:
            if b.fc != a.fc or b.address >= a.address + a.regs:
                break
            raise invalid(f"Kênh {a.key} và {b.key} chồng lấn thanh ghi", f"channels.{j}.address")
    if t.baud_codes:
        for k in t.baud_codes:
            if not k.isdigit() or int(k) not in BAUDRATES:
                raise invalid(f"Mã baud cho “{k}” không hợp lệ", "baud_codes")


# --- Thiết bị ------------------------------------------------------------------------------


class DeviceChannelIn(BaseModel):
    key: str
    label: str | None = Field(None, max_length=40)
    display_min: float | None = None
    display_max: float | None = None
    alarm_low: float | None = None
    alarm_high: float | None = None
    enabled: bool = True


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    zone: str = Field("", max_length=40)
    connection_id: int
    unit_id: int = Field(ge=0, le=255)
    template_id: int
    poll_interval_s: int = Field(10, ge=1, le=3600)
    enabled: bool = True
    channels: list[DeviceChannelIn] = []


def validate_device_channel(ch: DeviceChannelIn, tc: ChannelDef, field: str) -> None:
    """Kiểm tra khi lưu kênh (spec mục 4.3): thang từ < đến, nằm trong phạm vi hợp lệ, chứa cả hai ngưỡng."""
    if ch.alarm_low is not None and ch.alarm_high is not None and ch.alarm_low >= ch.alarm_high:
        raise invalid("Ngưỡng thấp phải nhỏ hơn ngưỡng cao", f"{field}.alarm_high")
    t_lo, t_hi = tc.effective_display()
    lo = ch.display_min if ch.display_min is not None else t_lo
    hi = ch.display_max if ch.display_max is not None else t_hi
    if lo is not None and hi is not None and lo >= hi:
        raise invalid("Thang hiển thị: “từ” phải nhỏ hơn “đến”", f"{field}.display_max")
    if ch.display_min is not None and tc.min is not None and ch.display_min < tc.min:
        raise invalid(f"Thang phải nằm trong phạm vi hợp lệ của mẫu (từ {tc.min:g})", f"{field}.display_min")
    if ch.display_max is not None and tc.max is not None and ch.display_max > tc.max:
        raise invalid(f"Thang phải nằm trong phạm vi hợp lệ của mẫu (đến {tc.max:g})", f"{field}.display_max")
    if ch.alarm_low is not None and lo is not None and ch.alarm_low < lo:
        raise invalid("Thang hiển thị phải chứa ngưỡng thấp", f"{field}.display_min")
    if ch.alarm_high is not None and hi is not None and ch.alarm_high > hi:
        raise invalid("Thang hiển thị phải chứa ngưỡng cao", f"{field}.display_max")

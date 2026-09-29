"""Bộ giải mã với frame thật của Node 01, 02, 03 (vector ở PLAN.md, mục Kiểm thử), gộp thanh ghi, chọn bucket,
kiểm tra thang hiển thị, định dạng số trong nhật ký."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import pytest
from vectors import NODE01_34, NODE01_86, NODE02, NODE02_EXC, NODE03, channel, frame, registers, templates

from greenhouse.core.decode import address_hint, alarm_state, decode, encode, evaluate, plan_blocks
from greenhouse.core.errors import ApiError
from greenhouse.core.models import ChannelDef, DeviceChannelIn, TemplateDef, validate_device_channel, validate_template
from greenhouse.sim.nodes import check_crc
from greenhouse.web.auditfmt import num, rng
from greenhouse.web.services.readings import choose_bucket


@pytest.mark.parametrize("hexstr", [NODE02, NODE01_34, NODE02_EXC, NODE01_86, NODE03])
def test_vector_crc(hexstr: str) -> None:
    assert check_crc(frame(hexstr))


def test_node02_climate_frame() -> None:
    regs = registers(NODE02)
    assert regs == [0x4207, 0x3333, 0x428E, 0xCCCD, 0x4715, 0x3800]
    t = templates()["Node nhiệt ẩm, ánh sáng"]
    values = {c.key: evaluate(c, regs, 0) for c in t.channels}
    assert values["temperature"].value == 33.8
    assert values["humidity"].value == 71.4
    assert values["illuminance"].value == 38200
    assert all(v.quality == "good" for v in values.values())


@pytest.mark.parametrize(("hexstr", "raw", "value"), [(NODE01_34, 34, 3.4), (NODE01_86, 86, 8.6)])
def test_node01_wind_frame(hexstr: str, raw: int, value: float) -> None:
    ch = channel("Node tốc độ gió", "wind_speed")
    d = evaluate(ch, registers(hexstr), block_start=ch.address)
    assert d.raw == raw
    assert d.value == value
    assert d.quality == "good"


def test_node03_co2_frame() -> None:
    ch = channel("Node CO2 (MQ135)", "co2")
    d = evaluate(ch, registers(NODE03), 0)
    assert d.value == 612
    assert ch.estimate is True


def test_exception_frame() -> None:
    f = frame(NODE02_EXC)
    assert f[0] == 2
    assert f[1] == 0x83  # FC 03 | 0x80
    assert f[2] == 2  # Illegal Data Address


def test_sensor_fault_codes() -> None:
    wind = channel("Node tốc độ gió", "wind_speed")
    d = evaluate(wind, [0x8000], 1)
    assert (d.quality, d.value) == ("sensor_fault", None)
    assert "-32768" in (d.detail or "")
    temp = channel("Node nhiệt ẩm, ánh sáng", "temperature")
    d = evaluate(temp, encode(float("nan"), "float32", "ABCD"), 0)
    assert (d.quality, d.value) == ("sensor_fault", None)


def test_out_of_range_is_kept_but_flagged() -> None:
    rh = channel("Node nhiệt ẩm, ánh sáng", "humidity")
    d = evaluate(rh, encode(130.0, "float32", "ABCD"), 2)
    assert d.quality == "out_of_range"
    assert d.value == 130


def test_scale_and_offset() -> None:
    ch = ChannelDef(key="t", label="T", fc=4, address=0, type="int16", scale=0.1, offset=-40)
    assert evaluate(ch, [encode(-15, "int16")[0]], 0).value == -41.5


@pytest.mark.parametrize("order", ["ABCD", "CDAB", "BADC", "DCBA"])
@pytest.mark.parametrize(("dtype", "value"), [("float32", 33.75), ("int32", -123456), ("uint32", 4_000_000_000)])
def test_encode_decode_roundtrip(order: str, dtype: str, value: float) -> None:
    assert decode(encode(value, dtype, order), dtype, order) == value


def test_byte_orders() -> None:
    # 33,8 ở bốn thứ tự byte (datasheet thường ghi dạng ABCD, CDAB, BADC, DCBA)
    assert decode([0x3333, 0x4207], "float32", "CDAB") == decode([0x4207, 0x3333], "float32", "ABCD")
    assert decode([0x0742, 0x3333], "float32", "BADC") == decode([0x4207, 0x3333], "float32", "ABCD")
    assert decode([0x3333, 0x0742], "float32", "DCBA") == decode([0x4207, 0x3333], "float32", "ABCD")
    assert decode([0xFFFF], "int16") == -1
    assert decode([0xFFFF], "uint16") == 65535
    assert math.isnan(decode(encode(float("nan"), "float32"), "float32"))


# --- Gộp thanh ghi --------------------------------------------------------------------------


def ch(key: str, address: int, dtype: str = "float32", fc: int = 4) -> ChannelDef:
    return ChannelDef(key=key, label=key, fc=fc, address=address, type=dtype, byte_order="ABCD")


def test_blocks_node02_is_one_request() -> None:
    blocks = plan_blocks(templates()["Node nhiệt ẩm, ánh sáng"].channels)
    assert [(b.fc, b.start, b.count) for b in blocks] == [(4, 0, 6)]


def test_blocks_gap_up_to_4_registers_merges() -> None:
    blocks = plan_blocks([ch("a", 0), ch("b", 6)])  # a: 0–1, khoảng trống 2–5 (4 thanh ghi)
    assert [(b.start, b.count) for b in blocks] == [(0, 8)]
    blocks = plan_blocks([ch("a", 0), ch("b", 7)])  # khoảng trống 5 thanh ghi
    assert [(b.start, b.count) for b in blocks] == [(0, 2), (7, 2)]


def test_blocks_split_by_function_code_and_125_limit() -> None:
    blocks = plan_blocks([ch("a", 0, fc=3), ch("b", 2, fc=4)])
    assert [(b.fc, b.start) for b in blocks] == [(3, 0), (4, 2)]
    many = [ch(f"c{i}", i * 4) for i in range(40)]  # 0–157
    blocks = plan_blocks(many)
    assert all(b.count <= 125 for b in blocks)
    assert sum(len(b.channels) for b in blocks) == 40
    assert len(blocks) == 2


# --- Bucket biểu đồ -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("span_h", "bucket_ms"),
    [(1, 0), (5, 0), (6, 60_000), (24, 60_000), (24 * 7, 600_000), (24 * 30, 1_800_000), (24 * 365, 21_600_000)],
)
def test_choose_bucket(span_h: int, bucket_ms: int) -> None:
    assert choose_bucket(span_h * 3_600_000, 2000, 10_000) == bucket_ms


def test_choose_bucket_never_exceeds_max_points() -> None:
    for span_h in (1, 3, 12, 48, 24 * 90, 24 * 400):
        b = choose_bucket(span_h * 3_600_000, 500, 10_000)
        points = span_h * 3_600_000 / (b or 10_000)
        assert points <= 500 or b == 86_400_000


# --- Thang hiển thị, ngưỡng, mẫu --------------------------------------------------------------


def field_of(fn: Callable[..., None], *args: Any) -> str | None:
    with pytest.raises(ApiError) as e:
        fn(*args)
    return e.value.field


def test_device_channel_display_range() -> None:
    temp = channel("Node nhiệt ẩm, ánh sáng", "temperature")  # hợp lệ -40…80, thang mẫu 0…50
    ok = DeviceChannelIn(key="temperature", display_min=10, display_max=40, alarm_low=18, alarm_high=32)
    validate_device_channel(ok, temp, "channels.temperature")
    bad = [
        (DeviceChannelIn(key="temperature", display_min=40, display_max=10), "channels.temperature.display_max"),
        (DeviceChannelIn(key="temperature", display_min=-50), "channels.temperature.display_min"),
        (DeviceChannelIn(key="temperature", display_max=90), "channels.temperature.display_max"),
        (DeviceChannelIn(key="temperature", alarm_low=30, alarm_high=20), "channels.temperature.alarm_high"),
        (DeviceChannelIn(key="temperature", display_max=30, alarm_high=32), "channels.temperature.display_max"),
        (DeviceChannelIn(key="temperature", display_min=20, alarm_low=18), "channels.temperature.display_min"),
    ]
    for body, field in bad:
        assert field_of(validate_device_channel, body, temp, "channels.temperature") == field


def test_template_validation_points_at_field() -> None:
    def tpl(**over: object) -> TemplateDef:
        c = {"key": "t", "label": "T", "fc": 4, "address": 0, "type": "float32", "byte_order": "ABCD", **over}
        return TemplateDef(name="x", category="climate", channels=[c])

    validate_template(tpl())
    assert field_of(validate_template, tpl(byte_order=None)) == "channels.0.byte_order"
    assert field_of(validate_template, tpl(min=0, max=100, display_min=-5)) == "channels.0.display_min"
    assert field_of(validate_template, tpl(min=10, max=5)) == "channels.0.max"
    assert field_of(validate_template, tpl(scale=0)) == "channels.0.scale"
    overlap = TemplateDef(
        name="x",
        category="climate",
        channels=[
            ChannelDef(key="a", label="A", address=0, byte_order="ABCD"),
            ChannelDef(key="b", label="B", address=1, byte_order="ABCD"),
        ],
    )
    assert field_of(validate_template, overlap) == "channels.1.address"
    dup = TemplateDef(
        name="x",
        category="climate",
        channels=[
            ChannelDef(key="a", label="A", address=0, byte_order="ABCD"),
            ChannelDef(key="a", label="B", address=4, byte_order="ABCD"),
        ],
    )
    assert field_of(validate_template, dup) == "channels.1.key"


def test_alarm_state_and_address_hint() -> None:
    assert alarm_state(33, 18, 32) == "high"
    assert alarm_state(17, 18, 32) == "low"
    assert alarm_state(25, 18, 32) is None
    assert alarm_state(25, None, None) is None
    assert "địa chỉ 0" in (address_hint(40001, 3) or "")
    assert "địa chỉ 9" in (address_hint(30010, 4) or "")
    assert address_hint(10, 4) is None


def test_vietnamese_number_format() -> None:
    assert num(38200) == "38.200"
    assert num(3.4) == "3,4"
    assert num(None) == "trống"
    assert rng(10, 40, "°C") == "10–40 °C"
    assert rng(None, 32) == "…–32"

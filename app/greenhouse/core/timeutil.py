"""Thời gian: lưu epoch mili giây UTC, hiển thị theo múi giờ cấu hình."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "Asia/Ho_Chi_Minh"


def now_ms() -> int:
    return int(time.time() * 1000)


@lru_cache(maxsize=16)
def zone(name: str | None) -> tzinfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone(timedelta(hours=7), "UTC+07:00")


def local(ms: int, tz: str | None) -> datetime:
    return datetime.fromtimestamp(ms / 1000, zone(tz))


def utc_offset_ms(tz: str | None, ms: int) -> int:
    off = local(ms, tz).utcoffset()
    return int(off.total_seconds() * 1000) if off else 0


def iso(ms: int, tz: str | None, millis: bool = False) -> str:
    return local(ms, tz).isoformat(timespec="milliseconds" if millis else "seconds")

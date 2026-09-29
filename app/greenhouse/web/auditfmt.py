"""Mô tả thay đổi cho nhật ký: "Nhiệt độ: thang hiển thị trống → 10–40 °C"."""

from __future__ import annotations

from typing import Any


def num(v: Any) -> str:
    if v is None or v == "":
        return "trống"
    if isinstance(v, bool):
        return "bật" if v else "tắt"
    if isinstance(v, (int, float)):
        f = float(v)
        if f.is_integer():
            return f"{int(f):,}".replace(",", ".")
        return f"{f:g}".replace(".", ",")
    return str(v)


def rng(lo: Any, hi: Any, unit: str = "") -> str:
    if lo is None and hi is None:
        return "trống"
    return f"{num(lo) if lo is not None else '…'}–{num(hi) if hi is not None else '…'} {unit}".strip()


def diff(old: dict[str, Any], new: dict[str, Any], labels: dict[str, str]) -> list[str]:
    out = []
    for key, label in labels.items():
        a, b = old.get(key), new.get(key)
        if a != b and not (a in (None, "") and b in (None, "")):
            out.append(f"{label}: {num(a)} → {num(b)}")
    return out

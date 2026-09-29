"""Truy vấn biểu đồ và xuất CSV (spec mục 6, 7).

Server chọn bucket sao cho mỗi kênh trả tối đa max_points điểm. Bucket dưới 5 phút đọc từ readings;
từ 5 phút trở lên gộp từ readings_5m, phần sau mốc đã gộp tính từ dữ liệu thô. Mỗi bucket có avg, min, max.
"""

from __future__ import annotations

import csv
import heapq
import io
import math
import sqlite3
from collections.abc import Iterator
from typing import Any

from ...core import db
from ...core.repo import template_defs
from ...core.timeutil import iso, utc_offset_ms

BUCKETS_MS = [
    60_000,
    120_000,
    300_000,
    600_000,
    900_000,
    1_800_000,
    3_600_000,
    7_200_000,
    10_800_000,
    21_600_000,
    43_200_000,
    86_400_000,
]
AGG_MS = 300_000
EXPORT_RES = {"raw": 0, "5m": 300_000, "1h": 3_600_000, "1d": 86_400_000}


def choose_bucket(span_ms: int, max_points: int, min_poll_ms: int) -> int:
    """0 là dữ liệu thô."""
    if span_ms / max(1, min_poll_ms) <= max_points:
        return 0
    for b in BUCKETS_MS:
        if span_ms / b <= max_points:
            return b
    return BUCKETS_MS[-1]


def channel_meta(conn: sqlite3.Connection, ids: list[int]) -> dict[int, dict[str, Any]]:
    if not ids:
        return {}
    tdefs = template_defs(conn)
    q = ",".join("?" * len(ids))
    out = {}
    for r in conn.execute(
        f"SELECT ch.id, ch.key, ch.label, ch.unit, ch.alarm_low, ch.alarm_high, d.name AS device_name, d.zone, "
        f"d.poll_interval_s, d.template_id FROM channels ch JOIN devices d ON d.id = ch.device_id WHERE ch.id IN ({q})",
        ids,
    ):
        tdef = tdefs.get(r["template_id"])
        cdef = next((c for c in tdef.channels if c.key == r["key"]), None) if tdef else None
        out[r["id"]] = {
            "label": r["label"],
            "unit": r["unit"],
            "zone": r["zone"],
            "device_name": r["device_name"],
            "alarm_low": r["alarm_low"],
            "alarm_high": r["alarm_high"],
            "poll_s": r["poll_interval_s"] or 10,
            "decimals": cdef.effective_decimals() if cdef else 1,
            "agg": cdef.agg if cdef else "mean",
        }
    return out


Row = tuple[int, float, float, float, int, float, float]  # ts, avg, min, max, count, sin_sum, cos_sum


def _combine(rows: list[Row], circular: bool) -> tuple[float, float, float, int]:
    n = sum(r[4] for r in rows)
    if circular:
        s = sum(r[5] for r in rows)
        c = sum(r[6] for r in rows)
        avg = math.degrees(math.atan2(s, c)) % 360
    else:
        avg = sum(r[1] * r[4] for r in rows) / n
    return avg, min(r[2] for r in rows), max(r[3] for r in rows), n


def _raw_rows(conn: sqlite3.Connection, cid: int, start: int, end: int) -> list[Row]:
    out = []
    for ts, v in conn.execute(
        "SELECT ts, value FROM readings WHERE channel_id = ? AND ts >= ? AND ts < ? AND quality = 0 ORDER BY ts",
        (cid, start, end),
    ):
        rad = math.radians(v)
        out.append((ts, v, v, v, 1, math.sin(rad), math.cos(rad)))
    return out


def _agg_rows(conn: sqlite3.Connection, cid: int, start: int, end: int) -> list[Row]:
    wm = db.get_setting(conn, "agg_watermark")
    wm = int(wm) if wm is not None else start
    out: list[Row] = []
    for ts, a, lo, hi, n, s, c in conn.execute(
        "SELECT ts, avg, min, max, count, sin_avg, cos_avg FROM readings_5m WHERE channel_id = ? AND ts >= ? AND ts < ? "
        "ORDER BY ts",
        (cid, start // AGG_MS * AGG_MS, min(end, wm)),
    ):
        rad = math.radians(a)
        out.append(
            (ts, a, lo, hi, n, (s if s is not None else math.sin(rad)) * n, (c if c is not None else math.cos(rad)) * n)
        )
    tail = max(start, wm)
    if tail < end:
        groups: dict[int, list[Row]] = {}
        for r in _raw_rows(conn, cid, tail, end):
            groups.setdefault(r[0] // AGG_MS * AGG_MS, []).append(r)
        for b, rs in sorted(groups.items()):
            n = len(rs)
            out.append(
                (
                    b,
                    sum(r[1] for r in rs) / n,
                    min(r[2] for r in rs),
                    max(r[3] for r in rs),
                    n,
                    sum(r[5] for r in rs),
                    sum(r[6] for r in rs),
                )
            )
    return out


def bucketed(
    conn: sqlite3.Connection, cid: int, start: int, end: int, bucket: int, tz: str, circular: bool = False
) -> list[tuple[int, float, float, float, int]]:
    """(mốc, trung bình, thấp nhất, cao nhất, số mẫu). bucket 0 là dữ liệu thô."""
    if bucket == 0:
        return [(r[0], r[1], r[2], r[3], 1) for r in _raw_rows(conn, cid, start, end)]
    base = _raw_rows(conn, cid, start, end) if bucket < AGG_MS else _agg_rows(conn, cid, start, end)
    off = utc_offset_ms(tz, (start + end) // 2)
    groups: dict[int, list[Row]] = {}
    for r in base:
        key = (r[0] + off) // bucket * bucket - off
        groups.setdefault(key, []).append(r)
    return [(k, *_combine(v, circular)) for k, v in sorted(groups.items())]


def history(
    conn: sqlite3.Connection, ids: list[int], start: int, end: int, max_points: int, tz: str, now: int
) -> dict[str, Any]:
    meta = channel_meta(conn, ids)
    min_poll = min((m["poll_s"] for m in meta.values()), default=10) * 1000
    bucket = choose_bucket(end - start, max_points, min_poll)
    series = []
    for cid in ids:
        m = meta.get(cid)
        if m is None:
            continue
        rows = bucketed(conn, cid, start, end, bucket, tz, m["agg"] == "circular_mean")
        interval = bucket or m["poll_s"] * 1000
        # Khoảng mất dữ liệu: dài hơn 3 lần chu kỳ, hoặc bucket rỗng (spec mục 7)
        limit = max(interval * 1.5, 3 * m["poll_s"] * 1000 + 5000)
        d = int(m["decimals"]) + 2
        points = [[t, round(a, d), round(lo, d), round(hi, d)] for t, a, lo, hi, _ in rows]
        gaps = [[p[0] + interval, q[0]] for p, q in zip(points, points[1:], strict=False) if q[0] - p[0] > limit]
        if points and end >= now - 60_000 and now - points[-1][0] > limit + interval:
            gaps.append([points[-1][0] + interval, now])
        stats = None
        if rows:
            n = sum(r[4] for r in rows)
            stats = {
                "min": round(min(r[2] for r in rows), d),
                "max": round(max(r[3] for r in rows), d),
                "avg": round(sum(r[1] * r[4] for r in rows) / n, d),
            }
        series.append(
            {
                "channel_id": cid,
                "label": m["label"],
                "unit": m["unit"],
                "zone": m["zone"],
                "device_name": m["device_name"],
                "decimals": m["decimals"],
                "alarm_low": m["alarm_low"],
                "alarm_high": m["alarm_high"],
                "interval_ms": interval,
                "points": points,
                "gaps": gaps,
                "stats": stats,
            }
        )
    return {"from": start, "to": end, "bucket_ms": bucket, "max_points": max_points, "series": series}


SPARK_BUCKET_MS = 60_000


def sparklines(conn: sqlite3.Connection, now: int, minutes: int = 60) -> dict[str, Any]:
    """Đường xu hướng trên thẻ: trung bình mỗi phút, kèm thấp nhất và cao nhất trong khoảng (thẻ HMI hiện cả hai).

    Truy vấn từng kênh để dùng khóa chính (channel_id, ts) của readings.
    """
    start = now - minutes * 60_000
    out: dict[str, Any] = {}
    ids = [
        r[0]
        for r in conn.execute(
            "SELECT ch.id FROM channels ch JOIN devices d ON d.id = ch.device_id WHERE d.deleted_at IS NULL"
        )
    ]
    for cid in ids:
        rows = conn.execute(
            "SELECT ts / 60000 * 60000 AS b, AVG(value), MIN(value), MAX(value) FROM readings "
            "WHERE channel_id = ? AND ts >= ? AND quality = 0 GROUP BY b ORDER BY b",
            (cid, start),
        ).fetchall()
        out[str(cid)] = {
            "points": [[r[0], round(r[1], 4)] for r in rows],
            "min": min((r[2] for r in rows), default=None),
            "max": max((r[3] for r in rows), default=None),
        }
    return {"from": start, "to": now, "bucket_ms": SPARK_BUCKET_MS, "channels": out}


def _col(m: dict[str, Any]) -> str:
    unit = f" ({m['unit']})" if m["unit"] else ""
    return f"{m['label']} · {m['zone']}{unit}" if m["zone"] else f"{m['label']}{unit}"


def export_csv(
    conn: sqlite3.Connection, ids: list[int], start: int, end: int, resolution: str, tz: str
) -> Iterator[str]:
    """Xuất theo luồng: UTF-8 có BOM, timestamp ISO 8601 kèm múi giờ, dấu chấm thập phân, dấu phẩy phân cách.

    Thô: dạng dài (timestamp, kênh, giá trị, chất lượng). Gộp: dạng rộng, mỗi kênh một cột, thẳng hàng theo bucket.
    """
    meta = channel_meta(conn, ids)
    ids = [i for i in ids if i in meta]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")

    def flush() -> str:
        s = buf.getvalue()
        buf.seek(0)
        buf.truncate()
        return s

    yield "﻿"
    if resolution == "raw":
        w.writerow(["timestamp", "kênh", "giá trị", "chất lượng"])
        yield flush()

        def rows_of(cid: int) -> Iterator[tuple[int, int, float, int]]:
            for ts, value, q in conn.execute(
                "SELECT ts, value, quality FROM readings WHERE channel_id = ? AND ts >= ? AND ts < ? ORDER BY ts",
                (cid, start, end),
            ):
                yield ts, cid, value, q

        for n, (ts, cid, value, q) in enumerate(heapq.merge(*(rows_of(c) for c in ids)), 1):
            w.writerow([iso(ts, tz, millis=True), _col(meta[cid]), value, "good" if q == 0 else "out_of_range"])
            if n % 2000 == 0:
                yield flush()
        yield flush()
        return

    bucket = EXPORT_RES[resolution]
    w.writerow(["timestamp"] + [_col(meta[c]) for c in ids])
    yield flush()
    data = {
        cid: {t: a for t, a, *_ in bucketed(conn, cid, start, end, bucket, tz, meta[cid]["agg"] == "circular_mean")}
        for cid in ids
    }
    off = utc_offset_ms(tz, start)
    t = (start + off) // bucket * bucket - off
    n = 0
    while t < end:
        row: list[Any] = [iso(t, tz)]
        for cid in ids:
            v = data[cid].get(t)
            row.append("" if v is None else round(v, int(meta[cid]["decimals"]) + 2))
        w.writerow(row)
        n += 1
        if n % 2000 == 0:
            yield flush()
        t += bucket
    yield flush()


def export_estimate(conn: sqlite3.Connection, ids: list[int], start: int, end: int, tz: str) -> dict[str, int]:
    raw = sum(
        int(
            conn.execute(
                "SELECT COUNT(*) FROM readings WHERE channel_id = ? AND ts >= ? AND ts < ?", (c, start, end)
            ).fetchone()[0]
        )
        for c in ids
    )
    off = utc_offset_ms(tz, start)
    out = {"raw": raw}
    for name, b in EXPORT_RES.items():
        if b:
            out[name] = max(0, (end - 1 + off) // b - (start + off) // b + 1)
    return out

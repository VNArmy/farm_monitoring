"""Collector với bus mô phỏng sim://: ghi lô, trạng thái thiết bị, lỗi theo kịch bản, đọc thử, quét, đổi địa chỉ,
nạp lại cấu hình không khởi động lại dịch vụ."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import AsyncIterator

import pytest

from greenhouse.collector import jobs, writer
from greenhouse.collector.bus import BusClient
from greenhouse.collector.service import Collector
from greenhouse.collector.worker import OFFLINE_AFTER, ConnectionWorker
from greenhouse.core import config, db
from greenhouse.core.repo import RuntimeConnection, RuntimeDevice
from greenhouse.seed import seed
from greenhouse.sim import nodes


def setup_bus(conn: sqlite3.Connection, name: str) -> None:
    seed(conn, f"sim://{name}", demo=True)
    # Không thử lại để test lỗi chạy nhanh; timeout dư so với độ trễ của bus mô phỏng (tới ~80 ms).
    conn.execute("UPDATE connections SET params = json_set(params, '$.timeout_ms', 300, '$.retries', 0, '$.gap_ms', 0)")


async def load(svc: Collector) -> None:
    await svc.dbx.run(db.migrate)
    svc.runtime, svc._saved, svc._templates = await svc.dbx.run(svc._load_all)


@pytest.fixture
async def svc(conn: sqlite3.Connection, request: pytest.FixtureRequest) -> AsyncIterator[Collector]:
    setup_bus(conn, request.node.name[:40])
    c = Collector(config.db_path())
    await load(c)
    yield c
    await c.stop()


def only_connection(svc: Collector) -> RuntimeConnection:
    return next(iter(svc.runtime.values()))


def device(svc: Collector, unit_id: int) -> RuntimeDevice:
    return next(d for d in only_connection(svc).devices if d.unit_id == unit_id)


def bus_of(svc: Collector) -> nodes.Bus:
    port = only_connection(svc).params.port  # type: ignore[union-attr]
    return nodes.get_bus(port.removeprefix("sim://"))


def latest(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {
        r["key"]: r
        for r in conn.execute(
            "SELECT ch.key, cl.* FROM channel_latest cl JOIN channels ch ON ch.id = cl.channel_id ORDER BY ch.id"
        )
    }


def events(conn: sqlite3.Connection, device_id: int) -> list[tuple[str, str | None]]:
    return [
        (r["type"], r["detail"])
        for r in conn.execute("SELECT type, detail FROM device_events WHERE device_id = ? ORDER BY id", (device_id,))
    ]


async def test_poll_all_nodes_batched_commit(svc: Collector, conn: sqlite3.Connection) -> None:
    w = ConnectionWorker(svc, only_connection(svc))
    try:
        for dev in only_connection(svc).devices:
            assert await w.poll(dev) is None
    finally:
        w.bus.close()
    # Chưa commit: ghi theo lô mỗi 5 giây.
    assert conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 0
    await svc.writer.flush()
    rows = latest(conn)
    assert set(rows) == {"wind_speed", "temperature", "humidity", "illuminance", "co2"}
    assert all(r["quality"] == "good" and r["value"] is not None for r in rows.values())
    assert conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 5
    states = [r[0] for r in conn.execute("SELECT state FROM device_status")]
    assert states == ["online"] * 3
    assert all(r[0] > 0 for r in conn.execute("SELECT last_rtt_ms FROM device_status"))
    assert tuple(conn.execute("SELECT SUM(requests), SUM(ok) FROM device_stats_5m").fetchone()) == (3, 3)


async def test_offline_after_three_timeouts_then_back_online(svc: Collector, conn: sqlite3.Connection) -> None:
    dev = device(svc, 2)
    bus_of(svc).set_fault(2, "silent")
    w = ConnectionWorker(svc, only_connection(svc))
    try:
        for i in range(OFFLINE_AFTER):
            err = await w.poll(dev)
            assert err is not None and err.kind == "timeout"
            expected = "offline" if i == OFFLINE_AFTER - 1 else "unknown"
            assert svc.dev_state(dev.id).state == expected
        bus_of(svc).set_fault(2, None)
        assert await w.poll(dev) is None
    finally:
        w.bus.close()
    await svc.writer.flush()
    assert events(conn, dev.id) == [("offline", "Không phản hồi"), ("online", "Sau 3 lần đọc lỗi")]
    st = conn.execute("SELECT * FROM device_status WHERE device_id = ?", (dev.id,)).fetchone()
    assert (st["state"], st["consecutive_failures"], st["last_error_kind"]) == ("online", 0, "timeout")
    assert tuple(conn.execute("SELECT timeout, ok FROM device_stats_5m WHERE device_id = ?", (dev.id,)).fetchone()) == (
        3,
        1,
    )
    # Lần đọc lỗi không ghi bản ghi đo
    n = conn.execute(
        "SELECT COUNT(*) FROM readings r JOIN channels ch ON ch.id = r.channel_id WHERE ch.device_id = ?", (dev.id,)
    ).fetchone()[0]
    assert n == 3


async def test_offline_backoff(svc: Collector) -> None:
    dev = device(svc, 2)
    bus_of(svc).set_fault(2, "silent")
    w = ConnectionWorker(svc, only_connection(svc))
    try:
        for _ in range(OFFLINE_AFTER + 1):
            err = await w.poll(dev)
            w._schedule(dev, err, due=time.monotonic(), lateness=0.0)
    finally:
        w.bus.close()
    # Offline thì giãn chu kỳ thử lại (tối đa 60 giây) để không chiếm bus của thiết bị khác.
    assert w.next_due[dev.id] - time.monotonic() > dev.poll_s * 2


async def test_bad_crc_counted_separately(svc: Collector, conn: sqlite3.Connection) -> None:
    dev = device(svc, 2)
    bus_of(svc).set_fault(2, "bad_crc")
    w = ConnectionWorker(svc, only_connection(svc))
    try:
        err = await w.poll(dev)
    finally:
        w.bus.close()
    assert err is not None and err.kind == "crc"
    await svc.writer.flush()
    assert tuple(
        conn.execute("SELECT crc, timeout FROM device_stats_5m WHERE device_id = ?", (dev.id,)).fetchone()
    ) == (1, 0)


async def test_sensor_fault_nan_and_minus_32768(svc: Collector, conn: sqlite3.Connection) -> None:
    bus_of(svc).set_fault(1, "sensor_fault")
    bus_of(svc).set_fault(2, "sensor_fault")
    w = ConnectionWorker(svc, only_connection(svc))
    try:
        assert await w.poll(device(svc, 1)) is None  # thiết bị vẫn trả lời: online, kênh lỗi cảm biến
        assert await w.poll(device(svc, 2)) is None
        await svc.writer.flush()
        rows = latest(conn)
        assert rows["wind_speed"]["quality"] == "sensor_fault"
        assert "-32768" in rows["wind_speed"]["detail"]
        for key in ("temperature", "humidity", "illuminance"):
            assert (rows[key]["quality"], rows[key]["value"], rows[key]["detail"]) == (
                "sensor_fault",
                None,
                "Node báo NaN",
            )
            assert rows[key]["fault_since"] is not None
        st = conn.execute("SELECT state, last_error_kind FROM device_status WHERE device_id = ?", (device(svc, 2).id,))
        assert tuple(st.fetchone()) == ("online", "sensor")
        bus_of(svc).set_fault(2, None)
        assert await w.poll(device(svc, 2)) is None
    finally:
        w.bus.close()
    await svc.writer.flush()
    assert latest(conn)["temperature"]["quality"] == "good"
    assert latest(conn)["temperature"]["fault_since"] is None
    types = [t for t, _ in events(conn, device(svc, 2).id)]
    assert types == ["sensor_fault"] * 3 + ["online"] + ["sensor_ok"] * 3


async def test_co2_nan_during_warmup(svc: Collector, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(nodes.settings, "warmup_s", 3600.0)
    w = ConnectionWorker(svc, only_connection(svc))
    try:
        assert await w.poll(device(svc, 3)) is None
    finally:
        w.bus.close()
    await svc.writer.flush()
    assert latest(conn)["co2"]["quality"] == "sensor_fault"


async def test_alarm_state(conn: sqlite3.Connection) -> None:
    setup_bus(conn, "alarm")
    conn.execute("UPDATE channels SET alarm_low = NULL, alarm_high = -30 WHERE key = 'temperature'")
    svc = Collector(config.db_path())
    await load(svc)
    w = ConnectionWorker(svc, only_connection(svc))
    try:
        await w.poll(device(svc, 2))
        await svc.writer.flush()
    finally:
        w.bus.close()
        await svc.stop()
    row = latest(conn)["temperature"]
    assert row["alarm"] == "high" and row["alarm_since"] == row["ts"]
    assert latest(conn)["humidity"]["alarm"] is None


# --- Lệnh từ web: đọc thử, quét, đổi địa chỉ -----------------------------------------------


def template_channels(conn: sqlite3.Connection, name: str) -> list[dict[str, object]]:
    import json

    r = conn.execute("SELECT definition FROM device_templates WHERE name = ?", (name,)).fetchone()
    return list(json.loads(r[0])["channels"])


async def test_test_read_shows_frames_and_highlights(svc: Collector, conn: sqlite3.Connection) -> None:
    cid = only_connection(svc).id
    res = await jobs.test_read(
        svc, {"connection_id": cid, "unit_id": 2, "channels": template_channels(conn, "Node nhiệt ẩm, ánh sáng")}
    )
    assert res["ok"] is True
    [req] = res["requests"]
    assert (req["fc"], req["address"], req["count"]) == (4, 0, 6)
    assert req["tx"].startswith("02 04 00 00 00 06")
    assert [h["start"] for h in req["highlights"]] == [3, 7, 11]
    assert [v["registers"] for v in res["values"]] == ["0–1", "2–3", "4–5"]
    assert all(v["quality"] == "good" for v in res["values"])


async def test_test_read_exception_hint(svc: Collector) -> None:
    cid = only_connection(svc).id
    ch = {"key": "t", "label": "T", "fc": 3, "address": 0, "type": "float32", "byte_order": "ABCD"}
    res = await jobs.test_read(svc, {"connection_id": cid, "unit_id": 2, "channels": [ch]})
    assert res["ok"] is False
    err = res["error"]
    assert (err["kind"], err["code"], err["name"]) == ("exception", 2, "Illegal Data Address")
    assert "FC 04" in err["hint"]
    res = await jobs.test_read(svc, {"connection_id": cid, "unit_id": 9, "channels": [{**ch, "fc": 4}]})
    assert res["error"]["kind"] == "timeout"
    assert "unit ID" in res["error"]["hint"]


async def test_test_read_with_unsaved_params(svc: Collector) -> None:
    cid = only_connection(svc).id
    port = only_connection(svc).params.port  # type: ignore[union-attr]
    ch = {"key": "co2", "label": "CO2", "fc": 4, "address": 0, "type": "float32", "byte_order": "ABCD"}
    res = await jobs.test_read(
        svc,
        {
            "connection_id": cid,
            "type": "rtu",
            "params": {"port": port, "baudrate": 4800, "timeout_ms": 400, "retries": 0},
            "unit_id": 1,
            "channels": [ch],
        },
    )
    assert res["ok"] is True  # cảm biến mới ở ID 1 · 4800


async def test_scan_finds_nodes_on_each_baud(svc: Collector) -> None:
    cid = only_connection(svc).id
    job = jobs.start_scan(svc, cid, {"from_id": 1, "to_id": 4, "bauds": [9600, 4800], "timeout_ms": 200})
    assert job.task is not None
    await job.task
    assert job.status == "done"
    found = [(f["unit_id"], f["baud"], f["response"]) for f in job.result["found"]]  # type: ignore[index]
    assert found == [(1, 4800, "ok"), (1, 9600, "ok"), (2, 9600, "ok"), (3, 9600, "ok")]
    assert job.progress["done"] == job.progress["total"] == 8


async def test_scan_cancel(svc: Collector) -> None:
    cid = only_connection(svc).id
    job = jobs.start_scan(svc, cid, {"from_id": 1, "to_id": 247, "bauds": [9600], "timeout_ms": 20})
    await asyncio.sleep(0.3)
    job.cancel = True
    assert job.task is not None
    await job.task
    assert job.status == "cancelled"
    assert job.result is not None and job.result["done"] < 247


async def test_set_address_and_baud(svc: Collector, conn: sqlite3.Connection) -> None:
    cid = only_connection(svc).id
    tid = conn.execute("SELECT id FROM device_templates WHERE name = 'Node CO2 (MQ135)'").fetchone()[0]
    res = await jobs.set_address(
        svc, cid, {"template_id": tid, "current_id": 1, "current_baud": 4800, "new_id": 4, "new_baud": 9600}
    )
    assert res["ok"] is True, res
    assert [s["ok"] for s in res["steps"]] == [True, True, True]
    client = BusClient("rtu", only_connection(svc).params)
    try:
        assert len((await client.read(4, 4, 0, 2)).regs) == 2
    finally:
        client.close()


async def test_set_address_requires_template_register(svc: Collector, conn: sqlite3.Connection) -> None:
    from greenhouse.core.errors import ApiError

    cid = only_connection(svc).id
    tid = conn.execute("SELECT id FROM device_templates WHERE name = 'Node tốc độ gió'").fetchone()[0]
    with pytest.raises(ApiError) as e:
        await jobs.set_address(svc, cid, {"template_id": tid, "current_id": 1, "new_id": 5})
    assert e.value.field == "template_id"


# --- Dịch vụ chạy thật: nạp lại cấu hình ----------------------------------------------------


async def test_service_polls_and_reload_applies_without_restart(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(writer, "FLUSH_INTERVAL_S", 0.2)
    setup_bus(conn, "service")
    svc = Collector(config.db_path())
    await svc.start()
    try:
        for _ in range(100):
            n = conn.execute("SELECT COUNT(*) FROM channel_latest WHERE quality = 'good'").fetchone()[0]
            if n == 5:
                break
            await asyncio.sleep(0.1)
        assert n == 5
        cid = only_connection(svc).id
        worker = svc.workers[cid]
        # Tắt Node 03: chỉ cập nhật danh sách thiết bị, worker giữ nguyên
        conn.execute("UPDATE devices SET enabled = 0 WHERE unit_id = 3")
        res = await svc.reload()
        assert res["restarted"] == []
        assert svc.workers[cid] is worker
        assert sorted(d.unit_id for d in worker.devices.values()) == [1, 2]
        # Đổi tham số cổng: chỉ worker của kết nối này khởi động lại
        conn.execute("UPDATE connections SET params = json_set(params, '$.timeout_ms', 150)")
        res = await svc.reload()
        assert res["restarted"] == [cid]
        assert svc.workers[cid] is not worker
        status = svc.status()
        assert status["workers"][0]["devices"] == 2
        assert status["last_commit_at"] is not None
    finally:
        await svc.stop()

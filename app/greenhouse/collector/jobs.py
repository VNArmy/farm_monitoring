"""Lệnh chạm vào bus theo yêu cầu của web: đọc thử, kiểm tra kết nối, quét địa chỉ, đổi địa chỉ và baud rate.

Lệnh giữ bus qua ConnectionWorker.exclusive() nên không tranh cổng với vòng đọc; web không bao giờ tự mở cổng.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..core.decode import evaluate, plan_blocks
from ..core.errors import conflict, invalid, not_found
from ..core.models import BAUDRATES, ChannelDef, RtuParams, TcpParams, TemplateDef, parse_params
from ..core.timeutil import now_ms
from .bus import BusClient, BusError

if TYPE_CHECKING:
    from .service import Collector
    from .worker import ConnectionWorker


def _hex(b: bytes) -> str:
    return b.hex(" ").upper()


def error_info(e: BusError, fc: int | None = None) -> dict[str, Any]:
    info: dict[str, Any] = {
        "kind": e.kind,
        "message": e.message,
        "code": e.code,
        "name": e.name,
        "fc": fc,
        "tx": _hex(e.tx),
        "rx": _hex(e.rx),
    }
    if e.kind == "exception":
        if e.code == 2 and fc == 3:
            info["hint"] = (
                "Đã đọc bằng FC 03 (holding). Thiết bị có thể chỉ có input register: đổi sang FC 04 trong mẫu, "
                "hoặc kiểm tra lại địa chỉ."
            )
        elif e.code == 2:
            info["hint"] = (
                "Exception 02 thường do sai địa chỉ thanh ghi hoặc sai function code. Kiểm tra địa chỉ (tính từ 0) "
                "và số thanh ghi của kiểu dữ liệu, hoặc thử FC 03."
            )
        elif e.code == 1:
            info["hint"] = "Thiết bị không hỗ trợ function code này. Thử đổi giữa FC 03 và FC 04."
        else:
            info["hint"] = "Thiết bị trả lời bằng exception. Xem datasheet của cảm biến."
    elif e.kind == "timeout":
        info["hint"] = "Không phản hồi. Kiểm tra unit ID, baud rate, parity, đấu dây A/B và nguồn cảm biến."
    elif e.kind == "crc":
        info["hint"] = (
            "Khung trả lời hỏng. Thường do nhiễu, thiếu điện trở đầu cuối 120 Ω, sai parity hoặc hai thiết bị trùng địa chỉ."
        )
    else:
        info["hint"] = "Kiểm tra cổng serial (adapter đã cắm chưa) hoặc địa chỉ mạng của kết nối."
    return info


def _target(svc: Collector, req: dict[str, Any]) -> tuple[str, RtuParams | TcpParams, ConnectionWorker | None]:
    """Kết nối cho lệnh: tham số đang nhập (chưa lưu) nếu có, không thì cấu hình đã lưu."""
    cid = req.get("connection_id")
    rc = svc.runtime.get(int(cid)) if cid is not None else None
    if req.get("params") is not None:
        conn_type = req.get("type") or (rc.type if rc else None)
        if conn_type not in ("rtu", "tcp"):
            raise invalid("Thiếu kiểu kết nối", "type")
        params = parse_params(conn_type, req["params"])
    elif rc is not None:
        conn_type, params = rc.type, rc.params
    elif cid is not None:
        saved = svc.saved_connection(int(cid))
        if saved is None:
            raise not_found("Không tìm thấy kết nối")
        conn_type, params = saved
    else:
        raise invalid("Thiếu kết nối", "connection_id")
    return conn_type, params, svc.worker_for(cid, params)


def _hold(worker: ConnectionWorker | None, reason: str) -> AbstractAsyncContextManager[None]:
    return worker.exclusive(reason) if worker is not None else nullcontext()


# --- Đọc thử và kiểm tra kết nối --------------------------------------------------------------


async def test_read(svc: Collector, req: dict[str, Any]) -> dict[str, Any]:
    conn_type, params, worker = _target(svc, req)
    unit = int(req["unit_id"])
    channels = [ChannelDef(**c) for c in req.get("channels", [])]
    if not channels:
        raise invalid("Mẫu chưa có kênh nào", "template_id")
    at = now_ms()
    requests: list[dict[str, Any]] = []
    values: list[dict[str, Any]] = []
    total = 0.0
    fc = None
    async with _hold(worker, "Đọc thử"):
        client = BusClient(conn_type, params, on_frame=worker.on_frame if worker else None)
        try:
            for b in plan_blocks(channels):
                fc = b.fc
                rr = await client.read(unit, b.fc, b.start, b.count, retries=0)
                total += rr.rtt_ms
                req_info: dict[str, Any] = {
                    "fc": b.fc,
                    "unit_id": unit,
                    "address": b.start,
                    "count": b.count,
                    "tx": _hex(rr.tx),
                    "rx": _hex(rr.rx),
                    "rtt_ms": round(rr.rtt_ms, 1),
                    "highlights": [],
                }
                for ch in b.channels:
                    off = ch.address - b.start
                    d = evaluate(ch, rr.regs, b.start)
                    req_info["highlights"].append(
                        {"key": ch.key, "start": rr.data_offset + off * 2, "len": ch.regs * 2}
                    )
                    values.append(
                        {
                            "key": ch.key,
                            "label": ch.label,
                            "unit": ch.unit,
                            "decimals": ch.effective_decimals(),
                            "registers": f"{ch.address}–{ch.address + ch.regs - 1}" if ch.regs > 1 else str(ch.address),
                            "raw_hex": " ".join(f"{r:04X}" for r in rr.regs[off : off + ch.regs]),
                            "raw": d.raw,
                            "value": d.value,
                            "quality": d.quality,
                            "detail": d.detail,
                        }
                    )
                requests.append(req_info)
        except BusError as e:
            return {"ok": False, "at": at, "requests": requests, "values": values, "error": error_info(e, fc)}
        finally:
            client.close()
    return {"ok": True, "at": at, "rtt_ms": round(total, 1), "requests": requests, "values": values}


async def test_connection(svc: Collector, req: dict[str, Any]) -> dict[str, Any]:
    conn_type, params, worker = _target(svc, req)
    at = now_ms()
    async with _hold(worker, "Kiểm tra kết nối"):
        client = BusClient(conn_type, params)
        try:
            await client.open()
            if isinstance(params, RtuParams):
                msg = f"mở cổng thành công với {params.baudrate} 8{params.parity}{params.stopbits}."
            else:
                msg = f"kết nối được {params.host}:{params.port}."
            ok = True
        except BusError as e:
            ok, msg = False, e.message
        finally:
            client.close()
    return {"ok": ok, "message": msg, "at": at}


# --- Quét địa chỉ -------------------------------------------------------------------------


@dataclass
class Job:
    id: int
    kind: str
    connection_id: int
    status: str = "running"  # running | done | error | cancelled
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    created_at: int = field(default_factory=now_ms)
    cancel: bool = False
    task: asyncio.Task[None] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "connection_id": self.connection_id,
            "status": self.status,
            "progress": self.progress,
            "result": self.result,
            "created_at": self.created_at,
        }


def start_scan(svc: Collector, cid: int, req: dict[str, Any]) -> Job:
    worker = svc.workers.get(cid)
    saved = svc.saved_connection(cid)
    if saved is None:
        raise not_found("Không tìm thấy kết nối")
    conn_type, params = (worker.rc.type, worker.rc.params) if worker else saved
    if any(j.connection_id == cid and j.status == "running" for j in svc.jobs.values()):
        raise conflict("Bus này đang được quét", "job_running")
    first = max(0 if conn_type == "tcp" else 1, int(req.get("from_id", 1)))
    last = min(255 if conn_type == "tcp" else 247, int(req.get("to_id", 247)))
    if first > last:
        raise invalid("“Từ ID” phải nhỏ hơn hoặc bằng “Đến ID”", "from_id")
    timeout_ms = max(20, min(2000, int(req.get("timeout_ms", 200))))
    bauds: list[int | None]
    if isinstance(params, RtuParams):
        bauds = [*sorted({int(b) for b in (req.get("bauds") or [params.baudrate]) if int(b) in BAUDRATES})]
        if not bauds:
            raise invalid("Chọn ít nhất một baud rate", "bauds")
    else:
        bauds = [None]
    job = svc.new_job("scan", cid)
    job.task = asyncio.create_task(_run_scan(svc, job, worker, conn_type, params, first, last, timeout_ms, bauds))
    return job


async def _run_scan(
    svc: Collector,
    job: Job,
    worker: ConnectionWorker | None,
    conn_type: str,
    params: RtuParams | TcpParams,
    first: int,
    last: int,
    timeout_ms: int,
    bauds: list[int | None],
) -> None:
    ids = list(range(first, last + 1))
    total = len(bauds) * len(ids)
    found: list[dict[str, Any]] = []
    done = 0
    started = time.monotonic()
    try:
        async with _hold(worker, "Quét địa chỉ"):
            for bi, baud in enumerate(bauds):
                client = BusClient(conn_type, params, baudrate=baud, timeout_ms=timeout_ms)
                client.retries = 0
                try:
                    for uid in ids:
                        if job.cancel:
                            break
                        if worker is not None:
                            worker.heartbeat = time.monotonic()
                        hit: dict[str, Any] | None = None
                        try:
                            rr = await client.read(uid, 4, 0, 1, retries=0)
                            hit = {"response": "ok", "rtt_ms": round(rr.rtt_ms, 1)}
                        except BusError as e:
                            # Exception 0A/0B là gateway báo không có thiết bị ở unit ID đó.
                            if e.kind == "exception" and e.code not in (10, 11):
                                hit = {"response": "exception", "code": e.code, "rtt_ms": None}
                            elif e.kind == "crc":
                                hit = {"response": "crc", "rtt_ms": None}
                            elif e.kind == "io":
                                raise
                        done += 1
                        if hit is not None:
                            hit.update(
                                {
                                    "unit_id": uid,
                                    "baud": baud,
                                    "parity": params.parity if isinstance(params, RtuParams) else None,
                                    "stopbits": params.stopbits if isinstance(params, RtuParams) else None,
                                }
                            )
                            found.append(hit)
                        elapsed = time.monotonic() - started
                        job.progress = {
                            "bauds": bauds,
                            "baud_index": bi,
                            "baud": baud,
                            "current_id": uid,
                            "from_id": first,
                            "to_id": last,
                            "done": done,
                            "total": total,
                            "found": list(found),
                            "eta_s": round(elapsed / done * (total - done)) if done else None,
                        }
                finally:
                    client.close()
                if job.cancel:
                    break
        job.result = {"found": found, "cancelled": job.cancel, "done": done, "total": total}
        job.status = "cancelled" if job.cancel else "done"
    except BusError as e:
        job.result = {"found": found, "error": e.message}
        job.status = "error"
    except asyncio.CancelledError:
        job.status = "cancelled"
        raise


# --- Đổi địa chỉ và baud rate -------------------------------------------------------------


async def set_address(svc: Collector, cid: int, req: dict[str, Any]) -> dict[str, Any]:
    saved = svc.saved_connection(cid)
    if saved is None:
        raise not_found("Không tìm thấy kết nối")
    worker = svc.workers.get(cid)
    conn_type, params = (worker.rc.type, worker.rc.params) if worker else saved
    tdef: TemplateDef | None = svc.template(int(req["template_id"]))
    if tdef is None or tdef.address_register is None:
        raise invalid("Mẫu chưa khai báo thanh ghi địa chỉ (FC 06)", "template_id")
    cur_id, new_id = int(req["current_id"]), int(req["new_id"])
    if not 1 <= new_id <= 247:
        raise invalid("Địa chỉ mới phải từ 1 đến 247", "new_id")
    base_baud = params.baudrate if isinstance(params, RtuParams) else None
    cur_baud = int(req.get("current_baud") or base_baud or 0) or None
    new_baud = int(req.get("new_baud") or cur_baud or 0) or None
    codes = tdef.baud_codes or {}
    if new_baud != cur_baud and (tdef.baud_register is None or str(new_baud) not in codes):
        raise invalid(f"Mẫu chưa khai báo thanh ghi baud rate hoặc mã cho {new_baud} baud", "new_baud")
    steps: list[dict[str, Any]] = []

    def fail(message: str) -> dict[str, Any]:
        return {"ok": False, "steps": steps, "message": message}

    async with _hold(worker, "Đổi địa chỉ"):
        client = BusClient(conn_type, params, baudrate=cur_baud)
        try:
            target = cur_id
            if new_id != cur_id:
                label = f"Ghi địa chỉ {new_id} vào thanh ghi địa chỉ (FC 06)"
                try:
                    await client.write_register(cur_id, tdef.address_register, new_id, retries=1)
                    steps.append({"label": label, "ok": True})
                    target = new_id
                except BusError as e:
                    steps.append({"label": label, "ok": False, "message": e.message})
                    return fail("Không ghi được địa chỉ mới. Thiết bị vẫn ở địa chỉ cũ.")
            if new_baud != cur_baud and tdef.baud_register is not None:
                label = f"Ghi mã baud {new_baud} vào thanh ghi baud rate (FC 06)"
                try:
                    await client.write_register(target, tdef.baud_register, int(codes[str(new_baud)]), retries=1)
                    steps.append({"label": label, "ok": True})
                except BusError as e:
                    steps.append({"label": label, "ok": False, "message": e.message})
                    return fail(f"Đã đổi địa chỉ sang {target} nhưng không ghi được baud rate.")
        finally:
            client.close()
        await asyncio.sleep(0.3)
        verify = BusClient(conn_type, params, baudrate=new_baud)
        label = f"Đọc lại ở ID {new_id}" + (f" · {new_baud}" if new_baud else "")
        try:
            try:
                await verify.read(new_id, 4, 0, 1, retries=2)
            except BusError as e:
                if e.kind != "exception":  # trả lời bằng exception vẫn xác nhận đã ở địa chỉ mới
                    raise
            steps.append({"label": label, "ok": True})
        except BusError as e:
            steps.append({"label": label, "ok": False, "message": e.message})
            note = " Một số model chỉ nhận baud rate mới sau khi tắt bật nguồn." if new_baud != cur_baud else ""
            return fail("Đã ghi nhưng chưa đọc lại được." + note)
        finally:
            verify.close()
    suffix = f" · {new_baud} baud" if new_baud else ""
    return {"ok": True, "steps": steps, "message": f"Thiết bị đang trả lời ở ID {new_id}{suffix}."}

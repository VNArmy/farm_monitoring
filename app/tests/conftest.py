"""Fixture dùng chung: mỗi test một CSDL tạm, bus mô phỏng không có lỗi ngẫu nhiên, collector giả là "đang dừng"."""

from __future__ import annotations

import socket
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from greenhouse.core import db
from greenhouse.sim import nodes


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("GREENHOUSE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GREENHOUSE_DB", str(tmp_path / "greenhouse.db"))
    monkeypatch.setenv("GREENHOUSE_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("GREENHOUSE_FRONTEND_DIST", str(tmp_path / "dist"))
    # Cổng không ai nghe: web thấy collector đang dừng ngay, không chờ timeout.
    monkeypatch.setenv("GREENHOUSE_COLLECTOR_SOCKET", f"tcp:127.0.0.1:{free_port()}")
    monkeypatch.delenv("GREENHOUSE_SIM_FAULTS", raising=False)
    # Bus mô phỏng tất định: không timeout, CRC lỗi ngẫu nhiên, CO2 không cần làm nóng.
    monkeypatch.setitem(nodes.settings, "timeout_rate", 0.0)
    monkeypatch.setitem(nodes.settings, "crc_rate", 0.0)
    monkeypatch.setitem(nodes.settings, "warmup_s", 0.0)
    nodes.reset_buses()
    from greenhouse.web import collector_client

    monkeypatch.setattr(collector_client, "_status_cache", (0.0, None))
    yield tmp_path
    nodes.reset_buses()


@pytest.fixture
def conn(isolated: Path) -> Iterator[sqlite3.Connection]:
    c = db.connect()
    db.migrate(c)
    yield c
    c.close()

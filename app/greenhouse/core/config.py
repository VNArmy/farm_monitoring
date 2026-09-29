"""Đường dẫn, cổng và địa chỉ socket, đọc từ biến môi trường GREENHOUSE_* để systemd ghi đè được."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = PACKAGE_DIR.parent


def _env_path(name: str, default: Path) -> Path:
    v = os.environ.get(name)
    return Path(v) if v else default


def data_dir() -> Path:
    return _env_path("GREENHOUSE_DATA_DIR", APP_DIR / "data")


def db_path() -> Path:
    return _env_path("GREENHOUSE_DB", data_dir() / "greenhouse.db")


def backup_dir() -> Path:
    return _env_path("GREENHOUSE_BACKUP_DIR", data_dir() / "backups")


def frontend_dist() -> Path:
    return _env_path("GREENHOUSE_FRONTEND_DIST", APP_DIR / "frontend" / "dist")


def seed_dir() -> Path:
    return _env_path("GREENHOUSE_SEED_DIR", APP_DIR / "seed")


WEB_HOST = os.environ.get("GREENHOUSE_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("GREENHOUSE_WEB_PORT", "8080"))

# Cổng HMI không đăng nhập nên luôn chỉ nghe loopback; không có biến nào đổi được host.
HMI_HOST = "127.0.0.1"
HMI_PORT = int(os.environ.get("GREENHOUSE_HMI_PORT", "8081"))


@dataclass(frozen=True)
class Endpoint:
    """Địa chỉ API nội bộ của collector: Unix socket trên Linux, TCP loopback khi phát triển trên Windows."""

    kind: str  # "unix" | "tcp"
    path: str = ""
    host: str = "127.0.0.1"
    port: int = 0

    def __str__(self) -> str:
        return f"unix:{self.path}" if self.kind == "unix" else f"tcp:{self.host}:{self.port}"


def collector_endpoint() -> Endpoint:
    raw = os.environ.get("GREENHOUSE_COLLECTOR_SOCKET")
    if not raw:
        raw = "unix:/run/greenhouse/collector.sock" if os.name == "posix" else "tcp:127.0.0.1:8090"
    if raw.startswith("unix:"):
        return Endpoint("unix", path=raw[5:])
    if raw.startswith("tcp:"):
        host, _, port = raw[4:].rpartition(":")
        return Endpoint("tcp", host=host or "127.0.0.1", port=int(port))
    return Endpoint("unix", path=raw)

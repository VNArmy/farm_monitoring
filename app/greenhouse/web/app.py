"""Tạo ứng dụng FastAPI.

kind="main": web app sau Caddy (127.0.0.1:8080): đăng nhập, dữ liệu, quản trị.
kind="hmi": cổng 127.0.0.1:8081 chỉ phục vụ trang /hmi và các endpoint /api/hmi/... chỉ đọc (spec mục 9).
Hai loại phân biệt bằng cổng, không bằng IP nguồn: request qua Caddy cũng đến từ 127.0.0.1.
"""

from __future__ import annotations

import hashlib
import html
import ipaddress
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..core import config, db
from ..core.errors import ApiError
from . import collector_client
from .auth import User, require_admin
from .live import Hub
from .routes import admin_connections, admin_devices, admin_system, admin_templates, admin_users, auth, data, hmi
from .routes import map as map_routes
from .services.hmi import hmi_config

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
SPA_PATHS = ["/", "/dang-nhap", "/bieu-do", "/ban-do", "/tai-khoan", "/quan-tri", "/quan-tri/{rest:path}"]
HMI_PATHS = ["/hmi", "/hmi/bieu-do"]
HTTP_CODES = {400: "invalid", 401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}
FIELD_NAMES = {
    "username": "Tên đăng nhập",
    "password": "Mật khẩu",
    "name": "Tên",
    "key": "Key",
    "label": "Nhãn",
    "address": "Địa chỉ",
    "unit_id": "Unit ID",
    "poll_interval_s": "Chu kỳ đọc",
    "timeout_ms": "Timeout",
    "port": "Port",
    "site_name": "Tên site",
    "site_lat": "Vĩ độ",
    "site_lng": "Kinh độ",
    "backup_time": "Giờ backup",
    "raw_retention_days": "Số ngày giữ dữ liệu thô",
}

_version_cache: dict[str, tuple[float, str]] = {}


def frontend_version() -> str:
    """Đổi khi có bản frontend mới; HMI tự tải lại khi thấy phiên bản khác."""
    dist = config.frontend_dist()
    parts = []
    for name in ("index.html", "hmi.html"):
        p = dist / name
        if not p.exists():
            continue
        mtime = p.stat().st_mtime
        cached = _version_cache.get(str(p))
        if cached is None or cached[0] != mtime:
            cached = (mtime, hashlib.sha256(p.read_bytes()).hexdigest()[:10])
            _version_cache[str(p)] = cached
        parts.append(cached[1])
    return f"{__version__}-" + "-".join(parts)


def tls_allowed(domain: str) -> bool:
    """Chỉ cấp chứng chỉ cho địa chỉ trong LAN: IP mạng riêng, *.local, tên máy của Pi, địa chỉ đặt ở Cài đặt."""
    d = domain.strip().lower().rstrip(".")
    if not d:
        return False
    try:
        ip = ipaddress.ip_address(d.strip("[]"))
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        pass
    host = socket.gethostname().lower()
    if d in (host, f"{host}.local", "localhost") or d.endswith(".local"):
        return True
    conn = db.connect()
    try:
        url = str(db.get_setting(conn, "public_url") or "")
    finally:
        conn.close()
    return bool(url) and urlsplit(url).hostname == d


def _page(name: str) -> Response:
    p = config.frontend_dist() / name
    if not p.exists():
        return HTMLResponse(
            "<!doctype html><meta charset=utf-8><title>Chưa build frontend</title>"
            "<p>Chưa có bản build của frontend. Chạy <code>npm ci && npm run build</code> trong thư mục frontend.</p>",
            status_code=503,
        )
    return HTMLResponse(p.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})


def _field(loc: tuple[Any, ...] | list[Any]) -> str:
    parts = [str(x) for x in loc if x not in ("body", "query", "path")]
    return ".".join(parts)


def _validation(errors: list[Any]) -> JSONResponse:
    e = errors[0] if errors else {}
    field = _field(e.get("loc", ()))
    last = field.split(".")[-1] if field else ""
    label = FIELD_NAMES.get(last, last)
    msg = str(e.get("msg", "không hợp lệ")).removeprefix("Value error, ")
    return JSONResponse(
        {"error": {"code": "invalid", "message": f"{label}: {msg}" if label else msg, "field": field or None}},
        status_code=400,
    )


def _docs_page(schema: dict[str, Any]) -> str:
    """Trang tài liệu API tự chứa, không tải gì từ CDN (spec mục 10: chạy offline)."""
    rows = []
    for path, ops in schema.get("paths", {}).items():
        for method, op in ops.items():
            tag = (op.get("tags") or [""])[0]
            params = ", ".join(p["name"] for p in op.get("parameters", []))
            rows.append(
                f"<tr><td>{html.escape(tag)}</td><td><b>{method.upper()}</b></td><td><code>{html.escape(path)}</code></td>"
                f"<td>{html.escape(op.get('summary', ''))}</td><td><code>{html.escape(params)}</code></td></tr>"
            )
    return (
        "<!doctype html><html lang=vi><meta charset=utf-8><title>API · Giám sát nhà kính</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#1C1E1B}table{border-collapse:collapse;width:100%}"
        "td,th{border-bottom:1px solid #E2E0D8;padding:6px 8px;text-align:left;vertical-align:top}</style>"
        f"<h1>API v{__version__}</h1><p><a href=/api/openapi.json>openapi.json</a> · thời gian là epoch mili giây UTC; "
        "request ghi cần header X-CSRF-Token.</p><table><tr><th>Nhóm</th><th>Phương thức</th><th>Đường dẫn</th>"
        "<th>Mô tả</th><th>Tham số</th></tr>" + "".join(rows) + "</table></html>"
    )


def create_app(kind: str = "main") -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        conn = db.connect()
        db.migrate(conn)
        conn.close()
        await app.state.hub.start()
        yield
        await app.state.hub.stop()
        await collector_client.aclose()

    app = FastAPI(
        title="Giám sát nhà kính",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.kind = kind
    extra = (lambda snap: {"hmi": hmi_config(db.thread_conn(), snap)}) if kind == "hmi" else None
    app.state.hub = Hub(frontend_version, extra)

    @app.middleware("http")
    async def guard(request: Request, call_next: Any) -> Response:
        path = request.url.path
        if kind == "hmi" and request.method not in ("GET", "HEAD"):
            return JSONResponse({"error": {"code": "read_only", "message": "Màn hình HMI chỉ xem", "field": None}}, 405)
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", CSP)
        if path.startswith("/assets/") or path.startswith("/fonts/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path.startswith("/map/"):
            # Tên file không có mã băm nên không để immutable.
            response.headers["Cache-Control"] = "public, max-age=604800"
        elif path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(exc.to_dict(), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = HTTP_CODES.get(exc.status_code, "error")
        return JSONResponse(
            {"error": {"code": code, "message": str(exc.detail), "field": None}}, status_code=exc.status_code
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _validation(list(exc.errors()))

    @app.exception_handler(ValidationError)
    async def model_validation(request: Request, exc: ValidationError) -> JSONResponse:
        return _validation(list(exc.errors()))

    if kind == "main":
        for r in (
            auth.router,
            data.router,
            map_routes.router,
            admin_users.router,
            admin_connections.router,
            admin_templates.router,
            admin_devices.router,
            admin_system.router,
        ):
            app.include_router(r)

        @app.get("/api/openapi.json", include_in_schema=False)
        def openapi(user: User = Depends(require_admin)) -> dict[str, Any]:
            return app.openapi()

        @app.get("/api/docs", include_in_schema=False)
        def docs(user: User = Depends(require_admin)) -> HTMLResponse:
            return HTMLResponse(_docs_page(app.openapi()))

        @app.get("/api/tls-ask", include_in_schema=False)
        def tls_ask(domain: str = "") -> Response:
            """Caddy hỏi trước khi cấp chứng chỉ nội bộ theo yêu cầu (deploy/Caddyfile)."""
            return Response(status_code=200 if tls_allowed(domain) else 403)

        for p in SPA_PATHS:
            app.add_api_route(p, lambda: _page("index.html"), methods=["GET"], include_in_schema=False)
    else:
        app.include_router(hmi.router)
        app.add_api_route("/", lambda: RedirectResponse("/hmi"), methods=["GET"], include_in_schema=False)
        for p in HMI_PATHS:
            app.add_api_route(p, lambda: _page("hmi.html"), methods=["GET"], include_in_schema=False)

    dist = config.frontend_dist()
    # Font và sprite của bản đồ chỉ có ở cổng web; màn HMI không có trang Bản đồ.
    for sub in ("assets", "fonts", "map") if kind == "main" else ("assets", "fonts"):
        d = dist / sub
        if d.is_dir():
            app.mount(f"/{sub}", StaticFiles(directory=d), name=sub)

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon() -> Response:
        p: Path = config.frontend_dist() / "favicon.svg"
        if not p.exists():
            return Response(status_code=404)
        return Response(p.read_bytes(), media_type="image/svg+xml")

    return app

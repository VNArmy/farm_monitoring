"""Dòng lệnh: greenhouse <lệnh> (hoặc python -m greenhouse <lệnh>).

migrate        Chạy migration CSDL (đánh số, chạy lặp lại không lỗi).
seed           Nạp cấu hình từ seed/ (Bus RS-485 số 1, 3 mẫu, Node 01, 02, 03).
create-admin   Tạo tài khoản quản trị đầu tiên (không có tài khoản mặc định).
passwd         Đặt lại mật khẩu một người dùng.
collector      Chạy dịch vụ collector.
web            Chạy dịch vụ web (web app và cổng HMI).
dev            Chạy thử trên máy phát triển với bus mô phỏng sim://demo và dữ liệu mẫu.
sim-tcp        Chạy simulator Modbus TCP (pymodbus server) cho Node 01, 02, 03.
backup         Backup CSDL ngay bằng VACUUM INTO.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import subprocess
import sys
from pathlib import Path

from .core import config, db
from .core.timeutil import now_ms


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # web hỏi trạng thái collector vài giây một lần; mỗi request một dòng log sẽ làm đầy journal trên thẻ nhớ.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _conn():
    conn = db.connect()
    db.migrate(conn)
    return conn


def _default_serial_port() -> str:
    byid = Path("/dev/serial/by-id")
    if byid.is_dir():
        ports = sorted(byid.iterdir())
        if ports:
            return str(ports[0])
    return "/dev/ttyUSB0"


def _create_user(conn, username: str, role: str, password: str, must_change: bool) -> None:
    from .web.auth import check_password_rules, hash_password

    check_password_rules(password)
    with db.tx(conn):
        conn.execute(
            "INSERT INTO users(username, password_hash, role, is_active, must_change_password, created_at) "
            "VALUES (?, ?, ?, 1, ?, ?)",
            (username, hash_password(password), role, int(must_change), now_ms()),
        )


def _ask_password(prompt: str = "Mật khẩu (tối thiểu 10 ký tự): ") -> str:
    p1 = getpass.getpass(prompt)
    p2 = getpass.getpass("Nhập lại: ")
    if p1 != p2:
        sys.exit("Hai lần nhập không khớp")
    return p1


def cmd_migrate(args: argparse.Namespace) -> None:
    conn = db.connect()
    applied = db.migrate(conn)
    print(f"CSDL {config.db_path()}: " + (f"đã chạy migration {applied}" if applied else "đã ở phiên bản mới nhất"))


def cmd_seed(args: argparse.Namespace) -> None:
    from .seed import SIM_PORT, seed

    conn = _conn()
    port = SIM_PORT if args.demo else (args.serial_port or _default_serial_port())
    if seed(conn, port, demo=args.demo):
        print(f"Đã nạp seed: Bus RS-485 số 1 ({port}, 9600 8N1), Node 01, 02, 03")
    else:
        print("CSDL đã có kết nối, bỏ qua seed")


def cmd_create_admin(args: argparse.Namespace) -> None:
    conn = _conn()
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (args.username,)).fetchone():
        sys.exit(f"Đã có người dùng {args.username}")
    password = args.password or _ask_password()
    try:
        _create_user(conn, args.username, "admin", password, must_change=False)
    except Exception as e:
        sys.exit(str(e))
    print(f"Đã tạo quản trị viên {args.username}")


def cmd_passwd(args: argparse.Namespace) -> None:
    from .web.auth import check_password_rules, hash_password

    conn = _conn()
    r = conn.execute("SELECT id FROM users WHERE username = ?", (args.username,)).fetchone()
    if r is None:
        sys.exit("Không có người dùng này")
    password = args.password or _ask_password()
    check_password_rules(password)
    with db.tx(conn):
        conn.execute(
            "UPDATE users SET password_hash = ?, is_active = 1, must_change_password = 0 WHERE id = ?",
            (hash_password(password), r[0]),
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (r[0],))
    print(f"Đã đặt lại mật khẩu cho {args.username}")


def cmd_collector(args: argparse.Namespace) -> None:
    from .collector.service import serve

    _setup_logging()
    asyncio.run(serve())


def cmd_web(args: argparse.Namespace) -> None:
    from .web.main import main

    _setup_logging()
    main()


def cmd_dev(args: argparse.Namespace) -> None:
    """Máy phát triển: bus mô phỏng, tài khoản demo admin/admin12345 và vanhanh/vanhanh-demo."""
    from .seed import SIM_PORT, backfill_demo, seed

    os.environ["GREENHOUSE_SIM"] = "1"
    if "GREENHOUSE_COLLECTOR_SOCKET" not in os.environ:
        os.environ["GREENHOUSE_COLLECTOR_SOCKET"] = (
            f"unix:{config.data_dir() / 'collector.sock'}" if os.name == "posix" else "tcp:127.0.0.1:8090"
        )
    conn = _conn()
    if seed(conn, SIM_PORT, demo=True):
        print("Đã tạo cấu hình demo trên bus mô phỏng sim://demo")
        _create_user(conn, "admin", "admin", "admin12345", must_change=False)
        _create_user(conn, "vanhanh", "viewer", "vanhanh-demo", must_change=False)
        print("Tài khoản demo: admin / admin12345 (quản trị), vanhanh / vanhanh-demo (xem)")
        print("Đang sinh 7 ngày dữ liệu mẫu...")
        n = backfill_demo(conn, days=7)
        print(f"Đã ghi {n:,} giá trị".replace(",", "."))
    conn.close()
    if not (config.frontend_dist() / "index.html").exists():
        print("Chưa build frontend: chạy `npm ci && npm run build` trong thư mục frontend")
    collector = subprocess.Popen([sys.executable, "-m", "greenhouse", "collector"], env=dict(os.environ))
    try:
        cmd_web(args)
    finally:
        collector.terminate()
        try:
            collector.wait(timeout=10)
        except subprocess.TimeoutExpired:
            collector.kill()


def cmd_sim_tcp(args: argparse.Namespace) -> None:
    from .sim.server import run_tcp

    _setup_logging()
    faults = {}
    for f in args.fault or []:
        uid, _, kind = f.partition(":")
        faults[int(uid)] = kind
    asyncio.run(run_tcp(args.host, args.port, args.framing, faults))


def cmd_backup(args: argparse.Namespace) -> None:
    from .collector.maintenance import run_backup

    _conn()
    info = run_backup()
    print(f"Đã backup {config.backup_dir() / info['file']} ({info['size']:,} byte)".replace(",", "."))


def main() -> None:
    p = argparse.ArgumentParser(prog="greenhouse", description="Giám sát nhà kính")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="chạy migration CSDL").set_defaults(func=cmd_migrate)

    s = sub.add_parser("seed", help="nạp cấu hình từ thư mục seed")
    s.add_argument("--serial-port", help="cổng adapter RS-485, mặc định cổng đầu tiên trong /dev/serial/by-id")
    s.add_argument("--demo", action="store_true", help="dùng bus mô phỏng và ngưỡng mẫu")
    s.set_defaults(func=cmd_seed)

    s = sub.add_parser("create-admin", help="tạo quản trị viên đầu tiên")
    s.add_argument("--username", default="admin")
    s.add_argument("--password", help="bỏ trống để nhập ẩn")
    s.set_defaults(func=cmd_create_admin)

    s = sub.add_parser("passwd", help="đặt lại mật khẩu")
    s.add_argument("username")
    s.add_argument("--password")
    s.set_defaults(func=cmd_passwd)

    sub.add_parser("collector", help="chạy collector").set_defaults(func=cmd_collector)
    sub.add_parser("web", help="chạy web app và cổng HMI").set_defaults(func=cmd_web)
    sub.add_parser("dev", help="chạy thử với bus mô phỏng").set_defaults(func=cmd_dev)

    s = sub.add_parser("sim-tcp", help="simulator Modbus TCP cho Node 01, 02, 03")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=5020)
    s.add_argument("--framing", choices=["tcp", "rtu"], default="tcp", help="tcp: Modbus TCP; rtu: RTU over TCP")
    s.add_argument("--fault", action="append", help="lỗi theo kịch bản, ví dụ 2:silent, 2:bad_crc, 3:sensor_fault")
    s.set_defaults(func=cmd_sim_tcp)

    sub.add_parser("backup", help="backup CSDL ngay").set_defaults(func=cmd_backup)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

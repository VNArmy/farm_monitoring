#!/usr/bin/env bash
# Cài hoặc nâng cấp hệ thống giám sát nhà kính trên Raspberry Pi 4/5 (Raspberry Pi OS Bookworm 64-bit, bản Lite).
#
#   sudo bash deploy/install.sh                       # cài mới hoặc nâng cấp; bus thật, cổng lấy từ /dev/serial/by-id
#   sudo bash deploy/install.sh --seed                # nạp cấu hình Bus RS-485 số 1, Node 01, 02, 03 (chỉ khi CSDL chưa có kết nối)
#   sudo bash deploy/install.sh --seed --serial-port /dev/serial/by-id/usb-FTDI_...
#   sudo bash deploy/install.sh --no-hmi              # Pi không cắm màn HDMI
#   sudo bash deploy/install.sh --rollback            # quay lại bản mã trước lần nâng cấp gần nhất
#
# Frontend phải build sẵn trên máy phát triển (npm ci && npm run build trong frontend/): Pi không cần Node.js.
# Chạy lại được nhiều lần; CSDL trong /var/lib/greenhouse được giữ nguyên, migration chạy lặp lại không lỗi.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
BASE=/opt/greenhouse
APP="$BASE/app"
PREV="$BASE/app.prev"
DATA=/var/lib/greenhouse
ETC=/etc/greenhouse
SEED=0
SERIAL_PORT=""
HMI=1
ROLLBACK=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --seed) SEED=1 ;;
    --serial-port) SERIAL_PORT="$2"; shift ;;
    --no-hmi) HMI=0 ;;
    --rollback) ROLLBACK=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Không hiểu tham số: $1" >&2; exit 2 ;;
  esac
  shift
done

if [[ $EUID -ne 0 ]]; then
  echo "Cần chạy bằng sudo" >&2
  exit 1
fi

run_as() { sudo -u greenhouse env GREENHOUSE_DATA_DIR="$DATA" "$@"; }

if [[ $ROLLBACK -eq 1 ]]; then
  [[ -d "$PREV" ]] || { echo "Không có bản trước để quay lại ($PREV)" >&2; exit 1; }
  echo "== Quay lại bản trước"
  systemctl stop greenhouse-web greenhouse-collector || true
  rm -rf "$APP.failed" && mv "$APP" "$APP.failed" && mv "$PREV" "$APP"
  systemctl start greenhouse-collector greenhouse-web
  systemctl try-restart greenhouse-hmi || true
  echo "Đã quay lại. Bản lỗi giữ ở $APP.failed. Migration không tự đảo ngược: nếu cần, khôi phục CSDL từ backup."
  exit 0
fi

if [[ ! -f "$SRC/frontend/dist/index.html" || ! -f "$SRC/frontend/dist/hmi.html" ]]; then
  echo "Chưa có frontend/dist: build trên máy phát triển (cd frontend && npm ci && npm run build) rồi chép cả thư mục sang Pi" >&2
  exit 1
fi

echo "== Gói hệ thống"
apt-get update -q
apt-get install -y -q python3 python3-venv curl rsync sqlite3 chrony caddy
if [[ $HMI -eq 1 ]]; then
  apt-get install -y -q cage
  if apt-cache show chromium-browser >/dev/null 2>&1; then
    apt-get install -y -q chromium-browser
    CHROMIUM=/usr/bin/chromium-browser
  else
    apt-get install -y -q chromium
    CHROMIUM=/usr/bin/chromium
  fi
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "== Cài uv"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi

echo "== Tài khoản dịch vụ"
id greenhouse >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin greenhouse
usermod -aG dialout greenhouse
install -d -o greenhouse -g greenhouse -m 750 "$DATA"
install -d -m 755 "$ETC"
[[ -f "$ETC/greenhouse.env" ]] || install -m 644 "$SRC/deploy/greenhouse.env.example" "$ETC/greenhouse.env"
if [[ $HMI -eq 1 ]]; then
  id greenhouse-hmi >/dev/null 2>&1 || useradd --create-home --shell /usr/sbin/nologin greenhouse-hmi
  usermod -aG video,render,input greenhouse-hmi
fi

echo "== Chép mã vào $APP (giữ bản cũ ở $PREV để quay lại)"
install -d "$BASE"
if [[ -d "$APP" ]]; then
  rm -rf "$PREV"
  cp -a "$APP" "$PREV"
fi
rsync -a --delete \
  --exclude .venv --exclude data --exclude __pycache__ --exclude .pytest_cache --exclude .mypy_cache \
  --exclude .ruff_cache --exclude frontend/node_modules --exclude frontend/src \
  "$SRC/" "$APP/"
(cd "$APP" && UV_PYTHON_PREFERENCE=only-system uv sync --frozen --no-dev --quiet)

echo "== CSDL"
run_as "$APP/.venv/bin/greenhouse" migrate
if [[ $SEED -eq 1 ]]; then
  if [[ -n "$SERIAL_PORT" ]]; then
    run_as "$APP/.venv/bin/greenhouse" seed --serial-port "$SERIAL_PORT"
  else
    run_as "$APP/.venv/bin/greenhouse" seed
  fi
fi

echo "== Đồng hồ, watchdog phần cứng, màn luôn sáng"
systemctl enable --now chrony
install -d /etc/systemd/system.conf.d
cat > /etc/systemd/system.conf.d/greenhouse-watchdog.conf <<'EOF'
[Manager]
RuntimeWatchdogSec=15
RebootWatchdogSec=2min
EOF
BOOT=/boot/firmware
[[ -d "$BOOT" ]] || BOOT=/boot
if [[ -f "$BOOT/config.txt" ]] && ! grep -q '^dtparam=watchdog=on' "$BOOT/config.txt"; then
  echo 'dtparam=watchdog=on' >> "$BOOT/config.txt"
fi
if [[ -f "$BOOT/cmdline.txt" ]] && ! grep -q 'consoleblank=0' "$BOOT/cmdline.txt"; then
  sed -i '1 s/$/ consoleblank=0/' "$BOOT/cmdline.txt"
fi
# journald: giới hạn dung lượng log trên thẻ nhớ
install -d /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/greenhouse.conf <<'EOF'
[Journal]
SystemMaxUse=200M
EOF

echo "== Dịch vụ systemd"
install -m 644 "$APP/deploy/systemd/greenhouse-collector.service" /etc/systemd/system/
install -m 644 "$APP/deploy/systemd/greenhouse-web.service" /etc/systemd/system/
install -m 644 "$APP/deploy/Caddyfile" /etc/caddy/Caddyfile
if [[ $HMI -eq 1 ]]; then
  sed "s#@CHROMIUM@#${CHROMIUM}#" "$APP/deploy/systemd/greenhouse-hmi.service" > /etc/systemd/system/greenhouse-hmi.service
  install -m 644 "$APP/deploy/systemd/greenhouse-hmi-restart.service" /etc/systemd/system/
  install -m 644 "$APP/deploy/systemd/greenhouse-hmi-restart.timer" /etc/systemd/system/
  # Chính sách Chromium: khóa DevTools, chặn tải file, chỉ mở được 127.0.0.1:8081
  for d in /etc/chromium/policies/managed /etc/chromium-browser/policies/managed; do
    install -d "$d"
    install -m 644 "$APP/deploy/chromium-policy.json" "$d/greenhouse.json"
  done
fi
systemctl daemon-reload
systemctl enable greenhouse-collector greenhouse-web
systemctl restart greenhouse-collector greenhouse-web
systemctl reload caddy 2>/dev/null || systemctl restart caddy
if [[ $HMI -eq 1 ]]; then
  systemctl enable greenhouse-hmi greenhouse-hmi-restart.timer
  systemctl start greenhouse-hmi-restart.timer
  systemctl set-default graphical.target
  systemctl restart greenhouse-hmi || true
fi

if ! run_as "$APP/.venv/bin/python" -c "
import sqlite3, sys
from greenhouse.core import config
c = sqlite3.connect(config.db_path())
sys.exit(0 if c.execute('SELECT COUNT(*) FROM users WHERE role = \"admin\"').fetchone()[0] else 1)
"; then
  echo
  echo "== Chưa có quản trị viên: tạo tài khoản đầu tiên (không có tài khoản mặc định)"
  run_as "$APP/.venv/bin/greenhouse" create-admin --username admin
fi

IP="$(hostname -I | awk '{print $1}')"
echo
echo "Xong. Web app: https://${IP}   ·   Màn HMI trên Pi: http://127.0.0.1:8081/hmi"
echo "Log: journalctl -u greenhouse-collector -u greenhouse-web -f"
echo "CA gốc cho tablet, điện thoại: /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt"
if grep -q 'dtparam=watchdog=on' "$BOOT/config.txt" 2>/dev/null; then
  echo "Khởi động lại Pi một lần để bật watchdog phần cứng và tắt screen blanking."
fi

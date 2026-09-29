# Giám sát nhà kính

Hệ thống giám sát nhà kính chạy trên Raspberry Pi: đọc cảm biến Modbus RTU/TCP, lưu SQLite, web app cho điện thoại và tablet trong LAN, màn HMI trên HDMI của chính Pi. Yêu cầu và kế hoạch ở [SPEC.md](../SPEC.md) và [PLAN.md](../PLAN.md).

## Kiến trúc

| Dịch vụ | Chạy gì | Ghi chú |
| --- | --- | --- |
| `greenhouse-collector` | `greenhouse collector` | Process duy nhất chạm vào bus. Mỗi kết nối một worker asyncio (pymodbus 3.15), gộp thanh ghi thành khối, ghi lô mỗi 5 giây, gộp `readings_5m`, backup hằng đêm. API nội bộ qua Unix socket `/run/greenhouse/collector.sock`. Báo sống cho systemd watchdog. |
| `greenhouse-web` | `greenhouse web` | FastAPI. Cổng `127.0.0.1:8080` sau Caddy: đăng nhập, dữ liệu, quản trị, SSE. Cổng `127.0.0.1:8081`: chỉ trang `/hmi` và `/api/hmi/*` chỉ đọc, không đăng nhập. |
| `greenhouse-hmi` | cage + Chromium kiosk | Chỉ là trình duyệt mở `http://127.0.0.1:8081/hmi`. `MemoryMax=1G`, `OOMScoreAdjust=500`, khởi động lại mỗi đêm lúc 4 giờ. |
| Caddy | reverse proxy | HTTPS chứng chỉ nội bộ cho LAN; không chuyển tiếp cổng 8081. |

Thời gian trong API và CSDL là epoch mili giây UTC; giao diện hiển thị theo múi giờ của site (mặc định `Asia/Ho_Chi_Minh`).

```
app/
  greenhouse/
    core/        cấu hình, CSDL và migration đánh số, giải mã Modbus, model
    collector/   worker từng bus, ghi lô, gộp dữ liệu, backup, API nội bộ, quét và đổi địa chỉ
    web/         FastAPI: xác thực, SSE, dữ liệu, quản trị, cổng HMI
    sim/         bus mô phỏng sim:// và simulator Modbus TCP cho Node 01, 02, 03
  frontend/      Vue 3 + Vite + TypeScript + uPlot; 2 entry: web app (index.html) và HMI (hmi.html)
  seed/          cấu hình ban đầu: Bus RS-485 số 1, 3 mẫu thiết bị, Node 01, 02, 03
  deploy/        install.sh, unit systemd, Caddyfile, policy Chromium
  tests/         pytest: giải mã theo frame thật, bus, collector, bảo trì, API
```

## Chạy thử trên máy phát triển

Cần Python 3.11 trở lên, [uv](https://docs.astral.sh/uv/) và Node.js 20.

```bash
cd app
uv sync                                   # tạo .venv theo uv.lock, gồm cả công cụ dev
cd frontend && npm ci && npm run build && cd ..
uv run greenhouse dev
```

`greenhouse dev` dùng bus mô phỏng `sim://demo` (Node 01 gió, Node 02 nhiệt ẩm ánh sáng, Node 03 CO2), sinh 7 ngày dữ liệu mẫu ở lần chạy đầu và tạo 2 tài khoản demo:

| Tài khoản | Mật khẩu | Vai trò |
| --- | --- | --- |
| `admin` | `admin12345` | Quản trị viên |
| `vanhanh` | `vanhanh-demo` | Người xem |

Mở http://127.0.0.1:8080 cho web app và http://127.0.0.1:8081/hmi cho màn HMI. Thêm `?touch=1` vào địa chỉ HMI để xem bản có cảm ứng (rail, ngăn kéo có mã QR, biểu đồ); `?touch=0` để ép bản chỉ có thẻ.

Sửa giao diện có tự tải lại: để `greenhouse dev` chạy, rồi trong `frontend/` chạy `npm run dev` và mở http://localhost:5173/ (HMI: http://localhost:5173/hmi.html). Vite chuyển `/api` tới 8080 và `/api/hmi` tới 8081.

Dữ liệu dev nằm trong `app/data/` (bỏ qua khi commit); đặt `GREENHOUSE_DATA_DIR` để dùng thư mục khác. Xóa thư mục đó để làm lại từ đầu.

Thử với Modbus TCP thay vì bus mô phỏng:

```bash
uv run greenhouse sim-tcp --port 5020                       # Modbus TCP
uv run greenhouse sim-tcp --port 5021 --framing rtu         # RTU over TCP
uv run greenhouse sim-tcp --fault 2:silent --fault 3:sensor_fault
```

Rồi thêm kết nối TCP `127.0.0.1:5020` ở trang Quản trị · Kết nối.

## Kiểm thử

```bash
cd app
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest -q
cd frontend && npm run build && npm test     # vue-tsc, build, vitest
```

CI chạy đúng các bước này (`.github/workflows/ci.yml`) và lưu `frontend/dist` làm artifact để chép lên Pi.

## Cài lên Raspberry Pi

Yêu cầu: Pi 4 hoặc 5 (4 GB), Raspberry Pi OS Bookworm 64-bit bản Lite, nên chạy từ SSD. Pi không cần Node.js: build frontend trên máy phát triển (hoặc lấy artifact CI) rồi chép cả thư mục `app/` kèm `frontend/dist` sang Pi.

```bash
# trên máy phát triển
cd app/frontend && npm ci && npm run build && cd ../..
rsync -a --exclude .venv --exclude data --exclude frontend/node_modules app/ pi@<địa-chỉ-pi>:~/greenhouse/

# trên Pi
cd ~/greenhouse
sudo bash deploy/install.sh --seed          # lần đầu: nạp cấu hình Bus RS-485 số 1, Node 01, 02, 03
sudo reboot                              # một lần, để bật watchdog phần cứng và tắt screen blanking
```

Script cài gói (Caddy, cage, Chromium, chrony), tạo user dịch vụ `greenhouse` (nhóm `dialout`) và `greenhouse-hmi`, chép mã vào `/opt/greenhouse/app`, tạo `.venv` bằng `uv sync --frozen`, chạy migration, cài unit systemd, Caddyfile và policy Chromium. Không có tài khoản mặc định: lần đầu script hỏi mật khẩu để tạo quản trị viên `admin` (hoặc chạy `sudo -u greenhouse GREENHOUSE_DATA_DIR=/var/lib/greenhouse /opt/greenhouse/app/.venv/bin/greenhouse create-admin`).

Tham số:

| Tham số | Tác dụng |
| --- | --- |
| `--seed` | Nạp cấu hình từ `seed/` nếu CSDL chưa có kết nối nào |
| `--serial-port <đường dẫn>` | Cổng adapter RS-485 cho seed; mặc định cổng đầu tiên trong `/dev/serial/by-id` |
| `--no-hmi` | Pi không cắm màn HDMI: bỏ cage, Chromium và dịch vụ `greenhouse-hmi` |
| `--rollback` | Quay lại bản mã trước lần nâng cấp gần nhất (giữ ở `/opt/greenhouse/app.prev`) |

Nâng cấp: chép mã mới sang Pi rồi chạy lại `sudo bash deploy/install.sh`. CSDL trong `/var/lib/greenhouse` giữ nguyên; migration chạy lặp lại không lỗi. Màn HMI tự tải lại khi thấy frontend mới.

Đường dẫn trên Pi:

| Đường dẫn | Nội dung |
| --- | --- |
| `/opt/greenhouse/app` | Mã và `.venv` |
| `/var/lib/greenhouse/greenhouse.db` | CSDL SQLite (WAL) |
| `/var/lib/greenhouse/backups` | Backup hằng đêm, giữ 7 bản (đổi ở Cài đặt) |
| `/etc/greenhouse/greenhouse.env` | Ghi đè cấu hình, ví dụ `GREENHOUSE_BACKUP_DIR=/mnt/greenhouse-backup` |

Nên đặt thư mục backup trên USB hoặc ổ khác: mount vào `/mnt/greenhouse-backup` (unit đã cho phép ghi ở đó), đặt `GREENHOUSE_BACKUP_DIR` trong `/etc/greenhouse/greenhouse.env` rồi `sudo systemctl restart greenhouse-collector greenhouse-web`.

### Mở web app trên điện thoại và tablet

Vào `https://<địa-chỉ-pi>` trong cùng mạng LAN (từ xa thì qua VPN như WireGuard hoặc Tailscale; không mở port ra Internet). Caddy tự tạo CA nội bộ nên lần đầu trình duyệt báo chứng chỉ chưa tin cậy. Để hết cảnh báo, cài CA gốc lên từng máy:

1. Trên Pi: `sudo cp /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt /tmp/greenhouse-ca.crt` rồi chép file sang điện thoại (USB, email nội bộ...).
2. Android: Cài đặt → Bảo mật → Mã hóa và thông tin xác thực → Cài chứng chỉ → Chứng chỉ CA.
3. iPhone/iPad: mở file để cài hồ sơ, rồi Cài đặt → Cài đặt chung → Giới thiệu → Cài đặt tin cậy chứng nhận → bật cho CA của Caddy.

Mã QR trên ngăn kéo của màn HMI mở đúng địa chỉ web app. Địa chỉ lấy từ IP LAN của Pi; đặt địa chỉ cố định ở Quản trị · Cài đặt nếu Pi có tên miền nội bộ.

## Vận hành

```bash
journalctl -u greenhouse-collector -u greenhouse-web -f      # log
systemctl status greenhouse-collector greenhouse-web greenhouse-hmi
sudo systemctl restart greenhouse-hmi                        # khởi động lại màn HMI (hoặc nút ở Cài đặt)
```

Lệnh `greenhouse` (chạy dưới user `greenhouse`, kèm `GREENHOUSE_DATA_DIR=/var/lib/greenhouse`):

| Lệnh | Tác dụng |
| --- | --- |
| `migrate` | Chạy migration CSDL |
| `seed [--serial-port P] [--demo]` | Nạp cấu hình ban đầu |
| `create-admin [--username U]` | Tạo quản trị viên |
| `passwd <user>` | Đặt lại mật khẩu, mở khóa và thu hồi mọi phiên của người đó |
| `backup` | Backup ngay bằng `VACUUM INTO` |
| `collector`, `web` | Chạy dịch vụ (systemd dùng) |
| `dev`, `sim-tcp` | Chạy thử trên máy phát triển |

Khôi phục từ backup:

```bash
sudo systemctl stop greenhouse-web greenhouse-collector
sudo -u greenhouse cp /var/lib/greenhouse/backups/greenhouse-YYYYMMDD-HHMMSS.db /var/lib/greenhouse/greenhouse.db
sudo rm -f /var/lib/greenhouse/greenhouse.db-wal /var/lib/greenhouse/greenhouse.db-shm
sudo systemctl start greenhouse-collector greenhouse-web
```

### Sự cố thường gặp

| Triệu chứng | Kiểm tra |
| --- | --- |
| Thẻ báo Mất kết nối, Chẩn đoán đếm Timeout | Sai unit ID hoặc baud rate, đấu ngược A/B, đứt dây, cảm biến mất nguồn. Dùng Quét bus để tìm địa chỉ thật. |
| Chẩn đoán đếm CRC | Nhiễu, thiếu điện trở đầu cuối 120 Ω, sai parity, 2 thiết bị trùng địa chỉ. Bật log frame thô 10 phút để xem khung hỏng. |
| Đọc thử báo Exception 02 | Sai địa chỉ thanh ghi hoặc function code: xem gợi ý quy đổi 4xxxx/3xxxx ở trang Mẫu, thử đổi giữa FC 03 và FC 04. |
| Thẻ báo Lỗi cảm biến | Node vẫn trả lời nhưng báo cảm biến bên trong hỏng (ví dụ Node 01 trả −32768). Kiểm tra đầu đo. |
| Kết nối báo Lỗi cổng | Adapter USB bị rút hoặc đổi tên: chọn lại cổng dạng `/dev/serial/by-id/...` ở trang Kết nối. |
| Banner Collector đang dừng | `journalctl -u greenhouse-collector -n 100`; cấu hình vẫn lưu được và áp dụng khi collector chạy lại. |
| Màn HMI trắng hoặc đứng | Nút Tải lại màn hình HMI ở Cài đặt, hoặc `sudo systemctl restart greenhouse-hmi`. Màn không cảm ứng chỉ hiện trang thẻ; thêm `?touch=1` trong unit nếu Chromium nhận sai. |
| Banner đồng hồ chưa đồng bộ | Pi không có RTC và chưa lấy được giờ NTP sau khi khởi động: kiểm tra mạng, `chronyc tracking`. |
| Trình duyệt báo chứng chỉ không tin cậy | Cài CA gốc của Caddy (mục trên). |

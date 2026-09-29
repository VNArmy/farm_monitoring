# Kế hoạch thực hiện: web app giám sát nhà kính

Sep 28, 2026 · @John Dao

## Tóm tắt

Giai đoạn 1 làm xong collector, web app (xem số liệu và admin) và màn HMI trên Pi theo Spec: Web app giám sát nhà kính trên Raspberry Pi và [bản thiết kế](https://claude.ai/artifact/Eoxoi2rZTAJiznVtCjuRpe), trong khoảng 51 ngày công: 10 tuần với một người làm toàn thời gian, khoảng 7 tuần nếu có hai người. Con số này chưa tính 20% dự phòng và thời gian chờ mua phần cứng.

Thứ tự bám lộ trình trong spec: collector phải đọc ổn định 72 giờ trên bàn thử thật rồi mới dựng giao diện, vì lỗi bus RS-485 rất khó tách khỏi lỗi phần mềm nếu cả hai cùng mới. Mỗi mốc kết thúc bằng một điều kiện kiểm được, không phải một ngày trên lịch.

| Mốc | Nội dung | Điều kiện qua |
| --- | --- | --- |
| M0 · Chuẩn bị | Bàn thử bus, Pi, repo, simulator | Pi đọc đúng cả ba node với cấu hình đã chốt |
| M1 · Thu thập | Collector, SQLite, cấu hình bằng file | 72 giờ đọc ổn định, lỗi dưới 0,5% |
| M2 · Xem dữ liệu | Đăng nhập, tổng quan, biểu đồ, CSV, màn HMI | Viewer bị chặn API admin (403); HMI tự lên sau khi cắt điện |
| M3 · Admin | User, kết nối, mẫu, thiết bị, chẩn đoán, cài đặt | Thêm cảm biến qua giao diện, có dữ liệu sau 1 phút |
| M4 · Vận hành | Quét bus, đổi địa chỉ, lưu giữ, backup, script cài đặt | Đạt đủ 10 kịch bản nghiệm thu |

## Việc cần chốt trước khi code

Các câu chặn M1 đã có đáp án ngày 29/09/2026, nên M0 chỉ còn đọc thử trên bàn để xác nhận, không phải dò. Còn ba việc mở, không việc nào chặn trước M2.

| Việc cần chốt | Đáp án | Cần trước |
| --- | --- | --- |
| Thứ tự word float32 | ABCD | M1 |
| Node 01: địa chỉ, hệ số tốc độ gió | Địa chỉ 1, chia 10 (đọc 86 là 8,6 m/s) | M1 |
| Baud rate, parity của bus | 9600 8N1 | M1 |
| CO2 | Node 03, input register 0, float32, cảm biến MQ135 | M1 |
| Màn HDMI | 10 inch, 1280 × 800; còn chờ: có cảm ứng không | M2 |
| Ánh sáng | lux; DLI chỉ là ước lượng | M2 |
| Thay MQ135 bằng cảm biến NDIR | Chưa quyết, xem phần Rủi ro | M3 |
| Cảm biến gió đặt ngoài trời không | Chưa trả lời; ngoài trời thì lắp chống sét cho RS-485 và nguồn | M4 |
| Truy cập từ xa trước khi làm cloud | Chưa trả lời; có thì cài WireGuard hoặc Tailscale ở M4 | M4 |

### Phần cứng cho bàn thử

Đặt mua ngay, vì thời gian giao hàng không nằm trong ước lượng:

- Raspberry Pi 4 hoặc Pi 5 bản 4 GB, SSD (USB 3, hoặc NVMe cho Pi 5), module RTC DS3231 cho Pi 4 hoặc pin RTC cho Pi 5.
- USB RS-485 tự điều khiển chiều truyền, 2 điện trở 120 Ω, cáp xoắn đôi chống nhiễu, nguồn cho node.
- Màn HDMI 10 inch 1280 × 800, đúng loại sẽ lắp thật.
- UPS mini hoặc HAT nguồn, để thử cắt điện có kiểm soát ở M4.
- Node 01, 02, 03 thật, cùng firmware sẽ lắp ở nhà kính; nếu chọn thay MQ135 thì mua cảm biến NDIR luôn đợt này.

## Lộ trình theo tuần

&#91;embedded content: lộ trình · 5 mốc theo tuần, một người làm\]

Phần backend của M2 chạy trong lúc collector đang thử 72 giờ; với hai người, frontend bắt đầu từ tuần 2 trên simulator nên M2 và M3 chồng lên nhau, tổng còn khoảng 7 tuần.

## M0 · Chuẩn bị

Có bàn thử bus chạy được và đủ công cụ để M1 không phải đoán: 4 ngày công.

| Việc | Đầu ra | Ngày |
| --- | --- | --- |
| Cài Pi: OS Lite 64-bit boot từ SSD, RTC, chrony, SSH | Pi khởi động không có mạng vẫn đúng giờ | 0,5 |
| Đấu bàn thử: 3 node, USB RS-485, 120 Ω hai đầu; đọc bằng `mbpoll` hoặc console pymodbus | Xác nhận cấu hình đã chốt; lưu frame thật của 3 node làm vector test | 1 |
| Repo, công cụ, CI (mục Repo và công cụ) | Lint và test chạy trên mỗi push | 1 |
| Simulator Modbus cho 3 node: pymodbus server, RTU qua cặp cổng ảo `socat`, TCP | Chạy collector và web trên laptop, không cần phần cứng | 1 |
| Thử cage + Chromium trên Pi với một trang tĩnh có SSE | Số RAM thật của Chromium; xác nhận bản 4 GB là đủ | 0,5 |

Điều kiện qua: Pi đọc đúng cả ba node với cấu hình đã chốt (ABCD, hệ số 0,1, 9600 8N1): số đọc khớp nhiệt kế, ẩm kế và máy đo gió cầm tay, Node 03 trả NaN trong lúc làm nóng rồi mới ra số.

## M1 · Thu thập

Collector chạy thật trên bàn thử, cấu hình nạp từ file JSON (mẫu ở spec mục 4.5), chưa có giao diện: 10 ngày công.

| Việc | Đầu ra | Ngày |
| --- | --- | --- |
| Schema SQLite, migration đánh số, nạp mẫu và thiết bị từ file | Lệnh migrate và seed chạy lặp lại không lỗi | 1,5 |
| Bộ giải mã: kiểu, thứ tự byte, hệ số, offset, mã lỗi, NaN, phạm vi hợp lệ | Qua test với frame thật của Node 01, 02, 03 | 1,5 |
| Lập lịch: gộp thanh ghi (cách nhau tối đa 4, tối đa 125), chu kỳ riêng từng thiết bị | Mỗi node đọc bằng đúng 1 request (Node 02: 6 thanh ghi) | 1 |
| Worker mỗi kết nối: RTU, TCP, RTU over TCP; timeout, thử lại, nghỉ giữa request, offline giãn tới 60 giây | Rút cáp một node, node còn lại vẫn đúng chu kỳ | 2 |
| Ghi lô 5 giây, `channel_latest`, `device_status`, sự kiện; gộp 5 phút và bù cửa sổ thiếu | Số liệu thô và số liệu gộp khớp nhau khi so bằng SQL | 1,5 |
| Unix socket API (status, reload, test-read); unit systemd có watchdog; log qua journald | Sửa file cấu hình, reload áp dụng mà không khởi động lại dịch vụ | 1,5 |
| Chạy thử 72 giờ, sửa lỗi phát hiện | Tỷ lệ lỗi theo từng thiết bị | 1 |

Chạy thử 72 giờ nằm trọn một cuối tuần nên không tốn thêm ngày công. Trong lúc chờ, M2 làm phần backend không đụng tới collector; giao diện chỉ bắt đầu khi mốc này qua.

Điều kiện qua: 72 giờ đọc liên tục, tỷ lệ lỗi dưới 0,5% mỗi thiết bị, collector không khởi động lại lần nào ngoài ý muốn.

## M2 · Xem dữ liệu

Người vận hành xem được số liệu trên điện thoại, tablet và màn HMI; cấu hình vẫn bằng file: 15 ngày công.

| Việc | Đầu ra | Ngày |
| --- | --- | --- |
| Khung FastAPI, lớp truy cập CSDL, OpenAPI | Trang tài liệu API chỉ mở cho admin | 0,5 |
| Đăng nhập: argon2id, session phía server, cookie, CSRF, tối đa 5 lần sai mỗi 10 phút, lệnh CLI tạo admin đầu tiên | Viewer gọi API admin nhận 403 | 1,5 |
| API dữ liệu: `/overview`, `/stream` (SSE), `/readings` chọn bucket từ bảng thô hoặc gộp, `/export.csv` theo luồng | Biểu đồ 30 ngày của 4 kênh dưới 2 giây trên Pi | 2 |
| Cổng HMI `127.0.0.1:8081`, Caddy HTTPS nội bộ | Từ máy khác trong LAN không vào được cổng 8081 | 1 |
| Frontend: màu, chữ, khoảng cách lấy từ bản thiết kế; khung điều hướng theo quy tắc đáp ứng (tab dưới, rail, sidebar) | Khung đúng ở 390, 600, 1280 và 1440 px | 2 |
| Trang đăng nhập; tổng quan với 5 trạng thái thẻ, SSE tự kết nối lại | Số mới hiện trong vòng 7 giây | 2,5 |
| Biểu đồ uPlot (2 trục, dải min-max, đứt đoạn khi mất dữ liệu); xuất CSV | File CSV mở đúng tiếng Việt trong Excel | 2,5 |
| Trang HMI: thẻ lớn, thanh dải đo theo thang hiển thị, ngăn kéo có mã QR, trạng thái chờ dữ liệu | Khớp bản thiết kế HMI ở 1280 × 800 | 1,5 |
| Dịch vụ `hmi`: cage + Chromium, policy, tắt screen blanking, giới hạn RAM, khởi động lại hằng đêm | HMI tự hiện số liệu sau khi cắt điện | 1,5 |

Thang hiển thị của thanh dải đo lấy từ file cấu hình ở mốc này; giao diện sửa thang đến ở M3.

Điều kiện qua: viewer bị chặn API admin (403), và màn HMI tự hiện số liệu sau khi cắt điện rồi cấp lại.

## M3 · Admin

Admin cấu hình mọi thứ trên giao diện; file cấu hình của M1 chỉ còn dùng làm seed: 12 ngày công.

| Việc | Đầu ra | Ngày |
| --- | --- | --- |
| API người dùng: thêm, đổi vai trò, đặt lại mật khẩu, khóa; không khóa được admin cuối cùng | Khóa user thì session của user đó bị thu hồi ngay | 1 |
| API kết nối: CRUD, danh sách `/dev/serial/by-id`, nút kiểm tra qua collector | Đổi timeout áp dụng trong 5 giây | 1 |
| API mẫu: CRUD, import và export JSON, kiểm tra kiểu, thứ tự byte, chồng lấn, phạm vi, thang hiển thị | Import lại file vừa export ra đúng mẫu cũ | 1 |
| API thiết bị và kênh: trùng unit ID trả 409, xóa mềm, ngưỡng và thang hiển thị, đọc thử cấu hình chưa lưu | Kịch bản trùng unit ID trong spec qua | 1 |
| Cài đặt, màn hình HMI, nhật ký thay đổi (trước, sau), chẩn đoán, log frame tự tắt sau 10 phút | Mọi thay đổi cấu hình có một dòng nhật ký | 1 |
| Trang Kết nối và hộp thoại thêm kết nối | Khớp bản thiết kế | 1 |
| Trang Mẫu thiết bị: bảng thanh ghi, bản đồ thanh ghi, panel kênh | Khớp bản thiết kế | 1,5 |
| Trang Thiết bị: form, bảng thang và ngưỡng có xem trước, Đọc thử hiện hex và exception | Exception 02 hiện đúng gợi ý | 1,5 |
| Trang Người dùng, Chẩn đoán, Cài đặt | Khớp bản thiết kế | 2,5 |
| Kiểm thử đầu cuối: sửa cấu hình trên giao diện tới lúc collector đọc theo cấu hình mới | Dưới 5 giây | 0,5 |

Điều kiện qua: thêm một cảm biến mới hoàn toàn qua giao diện (kết nối, mẫu, thiết bị) và có dữ liệu sau 1 phút.

## M4 · Vận hành và nghiệm thu

Hệ thống cài được lên Pi trắng bằng một script, tự lo lưu giữ và backup, qua đủ kịch bản nghiệm thu: 10 ngày công.

| Việc | Đầu ra | Ngày |
| --- | --- | --- |
| Quét bus (job nền, tiến độ, dừng, tạm dừng polling); đổi địa chỉ và baud có đọc lại xác nhận | Đổi địa chỉ một node mới trên bàn thử | 2,5 |
| Lưu giữ dữ liệu thô 365 ngày; backup `VACUUM INTO` giữ 7 bản, tải về; quy trình khôi phục | Khôi phục một bản backup lên Pi khác và chạy được | 1,5 |
| Script cài đặt: gói, user, group, 3 unit systemd, Caddy, chrony, RTC, policy Chromium; nâng cấp và quay lui | Pi trắng lên hệ thống chạy được trong 30 phút | 2 |
| Tài liệu vận hành: sự cố thường gặp, cài chứng chỉ Caddy lên điện thoại và tablet | Người khác làm theo được mà không cần hỏi | 1 |
| Nghiệm thu: 10 kịch bản trong spec, cắt điện 10 lần, chạy 72 giờ đủ 3 dịch vụ, đo hiệu năng và RAM | Biên bản nghiệm thu | 2 |
| Sửa lỗi phát hiện khi nghiệm thu | Mọi kịch bản qua ở lần chạy lại | 1 |

Điều kiện qua: đạt đủ 10 kịch bản nghiệm thu ở spec mục 11, trên Pi cài bằng script chứ không phải Pi dùng để phát triển.

## Repo và công cụ

Một repo cho cả ba dịch vụ, vì collector và web dùng chung model và bộ giải mã (spec mục 2).

```
greenhouse/
  core/        model, schema, migration, bộ giải mã dùng chung
  collector/   worker, lập lịch, ghi lô, gộp 5 phút, Unix socket
  web/         FastAPI: API chính và app cổng HMI
  frontend/    Vue 3 + Vite + TypeScript: app chính và entry HMI riêng
  deploy/      script cài đặt, unit systemd, Caddyfile, policy Chromium
  seed/        mẫu JSON của Node 01, Node 02
  tests/       unit, tích hợp với simulator, vector từ frame thật
```

- Python 3.11 trở lên, quản lý gói bằng uv có lockfile, ghim `pymodbus==3.15.*`; ruff, mypy, pytest.
- Frontend: Vue 3, Vite, TypeScript, uPlot, thư viện tạo QR chạy offline. Build sẵn thành file tĩnh, Pi không cần Node.js; trang HMI là một entry riêng để Chromium tải ít mã hơn.
- CI trên mỗi push: lint, test unit, test tích hợp với simulator, build frontend. Gắn tag phiên bản thì tạo gói cài đặt cho Pi (wheel, frontend đã build, thư mục deploy).
- Migration CSDL đánh số, tự chạy khi cài bản mới; không sửa migration đã phát hành.
- Mỗi mốc kết thúc bằng một tag và một bản cài lên bàn thử, không dồn cài đặt về cuối.

## Kiểm thử

Bốn tầng: hai tầng đầu chạy trên mỗi push, hai tầng sau chạy ở cuối mỗi mốc trên phần cứng thật.

| Tầng | Chạy ở đâu | Kiểm cái gì |
| --- | --- | --- |
| Unit | CI | Giải mã với frame thật, gộp thanh ghi, chọn bucket, kiểm tra thang hiển thị, định dạng số tiếng Việt |
| Tích hợp | CI | Collector và web chạy với simulator: timeout, CRC sai, exception, node mất rồi trở lại |
| Bàn thử | Pi và 3 node thật | Rút cáp, đổi cấu hình, quét bus, đổi địa chỉ, đo thời gian vòng đọc |
| Chạy dài và cắt điện | Pi và 3 node thật | 72 giờ không khởi động lại ngoài ý muốn; cắt điện 10 lần, `PRAGMA integrity_check` trả `ok` |

Vector test cho bộ giải mã lấy từ các frame đã có, CRC đã kiểm lại:

| Frame phản hồi | Giá trị đúng |
| --- | --- |
| `02 04 0C 42 07 33 33 42 8E CC CD 47 15 38 00 45 76` | 33,8 °C · 71,4 %RH · 38.200 lux |
| `01 04 02 00 22 39 29` | raw 34, tức 3,4 m/s với hệ số 0,1 |
| `02 83 02 30 F1` | Exception 02, Illegal Data Address |
| `01 04 02 00 56 39 0E` | raw 86, tức 8,6 m/s (ví dụ đã chốt) |
| `03 04 04 44 19 00 00 1D 73` | 612 ppm CO2, kênh ước tính |

Simulator phải phát được lỗi theo kịch bản (im lặng, CRC sai, trả NaN, trả -32768) để kiểm cờ `sensor_fault` và trạng thái offline mà không phải làm hỏng phần cứng.

## Rủi ro

Rủi ro lớn nhất là lỗi bus lẫn với lỗi phần mềm, nên bàn thử được dựng trước khi viết dòng code collector đầu tiên.

| Rủi ro | Dấu hiệu sớm | Cách giảm |
| --- | --- | --- |
| Lỗi bus RS-485 (nhiễu, thiếu 120 Ω, đấu ngược A/B) lẫn với lỗi phần mềm | Timeout, CRC lỗi rải rác trên bàn thử | Đọc bằng `mbpoll` trước khi có collector; log frame thô; thử dây ngắn trước, dây thật sau |
| Firmware node đổi thứ tự word, hệ số hay bảng thanh ghi giữa chừng | Giá trị vô lý hoặc lệch đúng 10 lần | Chốt ở M0 và ghi vào spec; mẫu thiết bị sửa bằng cấu hình, không sửa code |
| Chromium tốn RAM hơn dự kiến | Đo ở M0 vượt 600 MB | Pi 4 GB; `MemoryMax` cho dịch vụ `hmi`; phương án nhẹ hơn là trình duyệt WPE (cog) |
| Ổ lưu trữ hỏng do ghi liên tục | Lỗi I/O trong journald | Chạy từ SSD ngay từ M0; backup hằng ngày sang ổ khác |
| Sai giờ khi Pi khởi động không có mạng | Timestamp lệch so với đồng hồ thật | RTC có pin; chẩn đoán báo khi đồng hồ chưa đồng bộ |
| pymodbus đổi API ở bản tăng số giữa | Test tích hợp gãy khi nâng cấp | Ghim `3.15.*`; chỉ nâng cấp khi có lý do, chạy lại test với simulator |
| Ước lượng trượt | Một mốc vượt quá 30% số ngày | Cắt phạm vi trước khi dời lịch: DLI, VPD và biểu đồ trên HMI là phần cắt được đầu tiên |
| CO2 từ MQ135 sai lệch lớn: cảm biến nhạy amoniac, hơi benzen, khói và trôi theo nhiệt ẩm | CO2 nhảy khi bón phân, phun thuốc; không đổi theo lúc mở, đóng thông gió | Nhãn Ước tính, cảnh báo chỉ tham khảo; thay bằng cảm biến NDIR, giữ input register 0 kiểu float32 nên không phải sửa phần mềm |

## Giả định

- Một người làm toàn thời gian, quen Python và Vue, đã đọc spec và bản thiết kế. Hai người (một collector và backend, một frontend) thì frontend bắt đầu từ tuần 2 trên simulator và API giả lập theo OpenAPI, tổng còn khoảng 7 tuần.
- Firmware Node 01, 02, 03 do nhóm tự viết, sửa được khi cần (spec mục 12).
- Chưa tính: thời gian chờ mua phần cứng, lắp đặt tại nhà kính (tủ điện, kéo bus, chống sét), việc thay MQ135 bằng cảm biến NDIR và phần cloud.
- Khi hứa ngày với người khác, cộng thêm khoảng 20% dự phòng vào số ngày công ở trên.

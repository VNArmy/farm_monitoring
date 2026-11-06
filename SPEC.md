# Spec: Web app giám sát nhà kính trên Raspberry Pi

Sep 27, 2026 · @John Dao

## 1. Mục tiêu và phạm vi

Web app chạy cục bộ trên Raspberry Pi, đọc định kỳ 4 loại cảm biến qua Modbus RTU (RS-485) và Modbus TCP, lưu dữ liệu tại chỗ và hiển thị thông số đo. Admin quản lý người dùng và toàn bộ cấu hình Modbus qua giao diện web, không phải sửa file hay khởi động lại dịch vụ.

| Hạng mục | Trong phạm vi |
| --- | --- |
| Cảm biến | Nhiệt độ và độ ẩm, gió, ánh sáng, CO2 |
| Kết nối | Modbus RTU qua RS-485 (USB adapter); Modbus TCP (Modbus Ethernet), gồm thiết bị TCP gốc và gateway RS-485/Ethernet |
| Hiển thị thông số đo | Giá trị hiện tại theo thời gian thực, biểu đồ lịch sử, xuất CSV; màn hình HMI qua HDMI trên chính Pi (mục 7); tablet và điện thoại truy cập qua LAN |
| Admin dashboard | Quản lý user; cấu hình kết nối, mẫu thiết bị, thiết bị và địa chỉ Modbus; chẩn đoán; quét và đổi địa chỉ cảm biến |

Ngoài phạm vi giai đoạn này:

- EC, pH: thêm sau bằng một mẫu thiết bị mới trong admin, không sửa code (mục 4).
- Đồng bộ cloud: dữ liệu được giữ sẵn để đẩy bù về sau (mục 6).
- Điều khiển thiết bị chấp hành (quạt, cửa thông gió, phun sương). Lệnh ghi Modbus duy nhất là đổi địa chỉ hoặc baud rate cảm biến khi lắp đặt.
- Gửi cảnh báo ra ngoài (email, Telegram, Zalo). Giai đoạn này chỉ hiển thị trạng thái vượt ngưỡng trên giao diện.

## 2. Kiến trúc và công nghệ

Hệ thống gồm 2 dịch vụ chạy độc lập trên Pi và dùng chung một file SQLite: `collector` là process duy nhất mở cổng serial và kết nối Modbus TCP, `web` phục vụ giao diện và API.

&#91;embedded content: kiến trúc · 3 process trên Raspberry Pi, màn HDMI và trình duyệt qua LAN\]

Collector ghi dữ liệu vào SQLite; web đọc từ đó và chuyển các lệnh cần chạm vào bus (đọc thử, quét, đổi địa chỉ) sang collector qua Unix socket.

Màn HDMI của HMI chạy process thứ ba, `hmi`: cage và Chromium ở chế độ kiosk, mở trang HMI qua cổng loopback riêng của `web` (`127.0.0.1:8081`). Nó chỉ là một trình duyệt: không đọc CSDL, không chạm vào bus. Tablet và điện thoại vào `web` qua Caddy như mọi trình duyệt khác.

Lý do tách: khởi động lại hay cập nhật `web` không tạo lỗ hổng dữ liệu, và một truy vấn nặng (xuất CSV cả năm) không làm trễ chu kỳ đọc. Cái giá là phải có kênh giao tiếp giữa 2 process:

| Nhu cầu | Cơ chế |
| --- | --- |
| Cấu hình kết nối, mẫu, thiết bị | Lưu trong SQLite, nguồn sự thật duy nhất. Sau khi lưu, `web` gọi `POST /reload` của collector; collector chỉ khởi động lại worker của kết nối bị đổi |
| Lệnh chạm vào bus | `web` chuyển tiếp sang collector qua Unix socket. `web` không tự mở cổng serial: 2 process cùng ghi lên một bus half-duplex sẽ làm hỏng frame |
| Giá trị realtime | Collector cập nhật bảng `channel_latest` ở mỗi lần commit; `web` đọc bảng này mỗi 2 giây và đẩy thay đổi qua SSE |

Collector dừng thì cấu hình vẫn lưu được và áp dụng khi nó chạy lại; giao diện báo collector offline.

### Phương án đã cân nhắc

- Một process, polling chạy trong background task của FastAPI: triển khai đơn giản hơn, nhưng mỗi lần deploy web là một khoảng mất dữ liệu. Không chọn.
- Telegraf + InfluxDB + Grafana: Telegraf có sẵn plugin Modbus (RTU, TCP, RTU over TCP), Grafana có dashboard và phân quyền, gần như không phải viết code. Đổi lại, cấu hình Modbus nằm trong file TOML, không có công cụ quét hay đổi địa chỉ cảm biến, và stack nặng hơn trên Pi. Hợp lý nếu người cấu hình luôn là kỹ sư; spec này chọn app riêng vì yêu cầu cấu hình Modbus qua admin.

### Công nghệ

| Thành phần | Lựa chọn | Ghi chú |
| --- | --- | --- |
| Ngôn ngữ | Python ≥ 3.11 | Collector và web dùng chung model và bộ giải mã thanh ghi |
| Modbus | pymodbus (async client) + pyserial | Bản hiện tại 3.15.0 (13/08/2026), hỗ trợ sẵn RTU, TCP và RTU over TCP. Ghim `pymodbus==3.15.*`: dự án cho phép đổi API ở bản tăng số giữa ([PyPI](https://pypi.org/project/pymodbus/)) |
| Web | FastAPI, Uvicorn, Pydantic v2 | Tự sinh OpenAPI, kiểm tra dữ liệu đầu vào bằng Pydantic |
| Cơ sở dữ liệu | SQLite, chế độ WAL | Lý do ở mục 6 |
| Mật khẩu | argon2id (argon2-cffi) | Không có tài khoản mặc định |
| Frontend | Vue 3 + Vite, build sẵn thành file tĩnh | React cũng được nếu nhóm quen hơn; Pi không phải build |
| Biểu đồ | uPlot | Vẽ hàng chục nghìn điểm vẫn mượt trên máy yếu |
| Hệ thống | systemd, Caddy, chrony, cage + Chromium | Tự khởi động lại dịch vụ, HTTPS nội bộ và file tĩnh, đồng bộ giờ NTP, màn HMI kiosk trên HDMI |

## 3. Phần cứng và môi trường chạy

Pi cần RTC và ổ lưu trữ chịu ghi liên tục; thiếu một trong hai thì dữ liệu hoặc sai giờ, hoặc mất khi thẻ nhớ hỏng.

| Hạng mục | Yêu cầu | Lý do |
| --- | --- | --- |
| Board | Raspberry Pi 4 hoặc Pi 5, từ 4 GB RAM | Hai dịch vụ dưới 300 MB; Chromium của HMI thêm khoảng 300 đến 500 MB, bản 2 GB sẽ chật |
| Hệ điều hành | Raspberry Pi OS Lite 64-bit, thêm cage và Chromium | Không cần desktop đầy đủ: cage là compositor Wayland chỉ chạy một ứng dụng toàn màn hình, không có thanh tác vụ để thoát ra |
| Màn hình HMI | Màn HDMI cắm thẳng vào Pi; 10 inch 1280 × 800; cảm ứng qua USB chưa xác nhận | Cảm ứng để mở ngăn kéo và xem biểu đồ; màn không cảm ứng thì HMI chỉ hiện trang thẻ |
| Lưu trữ | SSD qua USB 3 (Pi 4) hoặc NVMe (Pi 5); tối thiểu là thẻ SD loại high-endurance | Ghi liên tục nhiều tháng làm mòn thẻ SD thường |
| Đồng hồ | Pi 5: RTC tích hợp, lắp pin. Pi 4: thêm module RTC, ví dụ DS3231 | Pi khởi động khi chưa có mạng sẽ gắn sai thời gian cho dữ liệu |
| RS-485 | USB adapter tự điều khiển chiều truyền | Loại chuyển chiều bằng phần mềm dễ trễ, gây va chạm frame |
| Nguồn | UPS mini hoặc HAT nguồn dự phòng (khuyến nghị) | Điện ở nhà kính thường chập chờn |

Ràng buộc của bus mà phần mềm phải phản ánh:

- Mọi thiết bị trên một bus RS-485 phải chung baud rate, parity, stop bits. Vì vậy tham số serial thuộc về kết nối, không thuộc về thiết bị. Cảm biến không chỉnh được về tham số chung thì cần bus thứ hai (adapter thứ hai).
- Cảm biến giá rẻ thường xuất xưởng cùng địa chỉ 1 và baud 4800 hoặc 9600. Phải đổi địa chỉ từng con trước khi cắm chung bus (công cụ ở mục 8).
- Cảm biến gió đặt ngoài trời: thêm chống sét lan truyền cho đường RS-485 và đường nguồn.
- Đấu nối vật lý theo sơ đồ bus ở bước trước: nối tiếp (daisy chain), điện trở 120 Ω ở hai đầu bus.

### Màn hình HMI trên Pi

Dịch vụ systemd `hmi` chạy `cage` và Chromium ở chế độ kiosk, mở `http://127.0.0.1:8081/hmi`. Vì Chromium chạy liên tục cạnh collector trên cùng một Pi, nó phải luôn là thứ bị hy sinh trước:

- Khởi động sau `web` và chờ cổng 8081 trả lời, để lúc boot không hiện trang lỗi.
- `Restart=always`; khởi động lại mỗi đêm lúc 4 giờ để xả bộ nhớ Chromium tích lũy khi chạy nhiều ngày.
- `MemoryMax=1G` và `OOMScoreAdjust=500` cho `hmi`, `OOMScoreAdjust=-500` cho collector: thiếu RAM thì hệ điều hành giết Chromium trước, không bao giờ giết collector.
- Tắt screen blanking của hệ điều hành để màn luôn sáng. Chromium dùng managed policy khóa DevTools, chặn tải file và chặn mọi URL ngoài `127.0.0.1:8081`.
- Không cắm bàn phím khi vận hành: Alt+F4 hay Ctrl+W đóng được kiosk. systemd mở lại sau vài giây, nhưng không nên để ngỏ đó.

## 4. Mô hình cấu hình Modbus

Cấu hình chia 4 cấp. Tách mẫu thiết bị khỏi thiết bị là điểm mấu chốt: thêm EC/pH, đổi model hay nhân nhiều cảm biến cùng loại đều chỉ là thao tác cấu hình.

| Cấp | Ý nghĩa | Ví dụ |
| --- | --- | --- |
| Kết nối | Một bus RTU (một cổng serial) hoặc một endpoint TCP | Bus RS-485 số 1; gateway khu B 192.168.1.50:502 |
| Mẫu thiết bị | Bảng thanh ghi của một model cảm biến, dùng lại cho nhiều thiết bị | Cảm biến nhiệt ẩm model X |
| Thiết bị | Một cảm biến cụ thể: kết nối + unit ID + mẫu + vị trí | Nhiệt ẩm khu A, ID 1 trên bus 1 |
| Kênh | Một đại lượng của một thiết bị; dữ liệu được lưu theo kênh | Nhiệt độ của Nhiệt ẩm khu A |

### 4.1 Kết nối RTU

| Trường | Giá trị | Mặc định |
| --- | --- | --- |
| Tên | text | bắt buộc |
| Cổng | Chọn từ danh sách `/dev/serial/by-id/*` | bắt buộc |
| Baud rate | 2400, 4800, 9600, 19200, 38400, 57600, 115200 | 9600 |
| Parity | N, E, O | N |
| Data bits, stop bits | 8; 1 hoặc 2 | 8, 1 |
| Timeout | ms | 500 |
| Số lần thử lại | 0 đến 3 | 1 |
| Nghỉ giữa 2 request | ms | 20 |
| Bật | có/không | có |

Dùng đường dẫn `/dev/serial/by-id/...` thay cho `/dev/ttyUSB0`: số thứ tự `ttyUSBx` có thể đổi sau khi khởi động lại hoặc cắm lại adapter, khiến bus bị gán nhầm cổng.

### 4.2 Kết nối TCP

| Trường | Giá trị | Mặc định |
| --- | --- | --- |
| Tên | text | bắt buộc |
| Host | IP hoặc hostname | bắt buộc |
| Port | 1 đến 65535 | 502 |
| Kiểu đóng gói | Modbus TCP hoặc RTU over TCP | Modbus TCP |
| Timeout | ms | 1000 |
| Số lần thử lại | 0 đến 3 | 1 |
| Bật | có/không | có |

- Modbus TCP: thiết bị TCP gốc, hoặc gateway RS-485/Ethernet chạy chế độ Modbus gateway (gateway tự chuyển TCP sang RTU).
- RTU over TCP: gateway chạy chế độ truyền trong suốt, frame RTU kèm CRC đi nguyên trong TCP.
- Collector gửi một request tại một thời điểm trên mỗi kết nối TCP: phía sau gateway vẫn là bus half-duplex, và nhiều gateway giá rẻ không xử lý request đồng thời.

### 4.3 Thiết bị

| Trường | Giá trị | Ghi chú |
| --- | --- | --- |
| Tên, khu vực | text | Khu vực dùng để nhóm trên màn hình hiển thị |
| Kết nối | chọn từ danh sách |  |
| Unit ID | RTU: 1 đến 247. TCP: 0 đến 255 | Thiết bị TCP gốc thường dùng 1 hoặc 255, xem datasheet |
| Mẫu thiết bị | chọn từ danh sách |  |
| Chu kỳ đọc | giây, tối thiểu 1 | Mặc định 10 |
| Bật | có/không |  |
| Thang hiển thị (mỗi kênh) | từ, đến; tùy chọn | Bỏ trống thì dùng thang mặc định của mẫu. Quyết định thanh dải đo trên màn hình HMI, không ảnh hưởng dữ liệu lưu |
| Ngưỡng cảnh báo (mỗi kênh) | thấp, cao; tùy chọn | Bỏ trống thì kênh không xét vượt ngưỡng |

Không cho lưu 2 thiết bị trùng unit ID trên cùng một kết nối.

Kiểm tra khi lưu kênh: thang hiển thị có giá trị từ nhỏ hơn giá trị đến, nằm trong phạm vi hợp lệ của mẫu và chứa cả hai ngưỡng nếu có; ngưỡng thấp nhỏ hơn ngưỡng cao. Form báo lỗi ngay tại ô sai và không tự nới thang, vì vạch ngưỡng nằm ngoài thang sẽ không vẽ được trên thanh dải đo.

### 4.4 Mẫu thiết bị và bảng thanh ghi

Mỗi mẫu là danh sách kênh; mỗi kênh mô tả cách đọc và giải mã một đại lượng.

| Trường | Giá trị | Ghi chú |
| --- | --- | --- |
| key | `temperature`, `humidity`, `wind_speed`, `wind_direction`, `illuminance`, `par`, `co2`... | Định danh ổn định cho API và chỉ số dẫn xuất |
| Nhãn, đơn vị | text | °C, %RH, m/s, °, lux, µmol/m²/s, ppm |
| Function code | 03 (holding) hoặc 04 (input) |  |
| Địa chỉ | 0 đến 65535, địa chỉ giao thức (0-based) | Xem lưu ý bên dưới |
| Kiểu dữ liệu | int16, uint16, int32, uint32, float32 |  |
| Thứ tự byte | ABCD, CDAB, BADC, DCBA | Chỉ cho kiểu 32 bit |
| Hệ số, offset | số thực | giá trị = raw × hệ số + offset |
| Phạm vi hợp lệ | min, max | Ngoài phạm vi: vẫn lưu, gắn cờ `out_of_range` |
| Thang hiển thị mặc định | min, max; tùy chọn | Thang của thanh dải đo trên màn hình HMI; từng thiết bị ghi đè được (mục 4.3). Bỏ trống thì dùng phạm vi hợp lệ |
| Mã lỗi | số nguyên, tùy chọn | Giá trị node trả khi cảm biến bên trong hỏng; với float32, NaN luôn được coi là lỗi |
| Cách gộp | `mean` hoặc `circular_mean` | `circular_mean` cho hướng gió: 350° và 10° phải ra 0°, không phải 180° |
| Số chữ số thập phân | 0 đến 3 | Chỉ ảnh hưởng hiển thị |
| Ước tính | có/không | Thẻ hiện nhãn Ước tính, cảnh báo của kênh chỉ để tham khảo; dùng cho cảm biến độ chính xác thấp như MQ135 |

Cấp mẫu có thêm 2 trường tùy chọn: thanh ghi địa chỉ và thanh ghi baud rate của model, dùng cho công cụ đổi địa chỉ (mục 8.5).

Lưu ý địa chỉ: datasheet hay ghi kiểu `40001` (quy ước 1-based kèm tiền tố loại thanh ghi) hoặc `0x0000` (địa chỉ giao thức). Form chỉ nhận địa chỉ giao thức và hiện gợi ý quy đổi: `40001` thành 0 với FC 03, `30010` thành 9 với FC 04. Lệch 1 địa chỉ là lỗi cấu hình Modbus hay gặp nhất.

Mẫu thực tế của các node đang dùng nằm ở mục 4.5.

Mẫu import/export được dưới dạng JSON; hệ thống cài sẵn mẫu của các node ở mục 4.5. Sửa mẫu chỉ ảnh hưởng dữ liệu đọc sau đó; dữ liệu cũ giữ nguyên giá trị đã quy đổi, và audit log ghi lại thay đổi để giải thích khi đồ thị đột ngột nhảy bậc.

### 4.5 Bảng thanh ghi thực tế của các node

Ba node đã chốt địa chỉ và bảng thanh ghi (29/09/2026): cùng bus RS-485 9600 8N1, cùng dùng input register (FC 04), địa chỉ giao thức tính từ 0, float32 thứ tự word ABCD.

| Node | Unit ID | Kênh | Địa chỉ | Kiểu | Số thanh ghi | Đơn vị | Hệ số |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Tốc độ gió | 1 | Tốc độ gió | 1 | int16 | 1 | m/s | 0.1 (đọc 86 là 8,6 m/s) |
| Nhiệt ẩm, ánh sáng | 2 | Nhiệt độ | 0 | float32 | 2 | °C | 1 |
| Nhiệt ẩm, ánh sáng | 2 | Độ ẩm | 2 | float32 | 2 | %RH | 1 |
| Nhiệt ẩm, ánh sáng | 2 | Ánh sáng | 4 | float32 | 2 | lux | 1 |
| CO2 | 3 | CO2 (ước tính, MQ135) | 0 | float32 | 2 | ppm | 1 |

Collector đọc mỗi node bằng đúng một request: Node 01 đọc 1 thanh ghi từ địa chỉ 1, Node 02 đọc 6 thanh ghi từ địa chỉ 0, Node 03 đọc 2 thanh ghi từ địa chỉ 0. Ánh sáng cần float32 (hoặc uint32): nắng trực tiếp vượt 100.000 lux, quá giới hạn 65.535 của uint16. Ba request ở 9600 baud mất dưới 1 giây trong mỗi chu kỳ 10 giây.

Quy ước firmware của các node:

- Thứ tự word của float32: ABCD (word cao ở địa chỉ thấp), đã chốt cho Node 02; Node 03 giả định cùng quy ước. MCU little-endian như ESP32, STM32 chép thẳng float vào 2 thanh ghi sẽ ra CDAB; khi đó 25,0 °C đọc thành khoảng 2,4 × 10⁻⁴¹. Firmware phải đảo word trước khi ghi vào thanh ghi.
- Mã lỗi khi cảm biến bên trong hỏng. Node gom nhiều cảm biến vẫn trả lời Modbus bình thường khi một cảm biến chết, nên collector không phân biệt được với giá trị thật. Đề xuất: kênh float32 trả NaN, kênh int16 của Node 01 trả -32768; collector gắn cờ `sensor_fault` (mục 5).
- Node 03 (MQ135) trả NaN cho tới khi cảm biến làm nóng xong sau mỗi lần cấp điện, để collector gắn cờ `sensor_fault` thay vì lưu số sai.
- Đổi địa chỉ qua admin (mục 8.5) chỉ dùng được nếu firmware có holding register chứa địa chỉ. Nếu địa chỉ cố định trong firmware hoặc chọn bằng DIP switch, bỏ trống trường này trong mẫu.

CO2 của Node 03 chỉ là ước tính. MQ135 là cảm biến bán dẫn oxit kim loại: nhà sản xuất liệt kê khí đích là amoniac, sulfide, hơi benzen và khói chứ không phải CO2, cần làm nóng hơn 48 giờ lần đầu, và điện trở cảm biến đổi theo nhiệt độ, độ ẩm. Trong nhà kính có phân bón chứa amoni và độ ẩm 70 đến 90%, số ppm quy đổi từ MQ135 không đủ tin để so ngưỡng, nên mẫu đánh dấu kênh này là ước tính (mục 4.4).

Khi thay bằng cảm biến NDIR (ví dụ Senseair S8, giao tiếp UART theo giao thức Modbus), giữ nguyên input register 0 kiểu float32 thì web app không phải sửa gì, chỉ bỏ cờ ước tính trong mẫu. Lưu ý cơ chế tự hiệu chỉnh nền (ABC) của cảm biến NDIR giả định cảm biến thường xuyên gặp không khí ngoài trời khoảng 400 ppm; nhà kính bơm CO2 hoặc đóng kín ban đêm thì nên tắt ABC và hiệu chỉnh tay.

Mẫu để import, dùng làm cấu hình seed cho M1:

```json
[
  {
    "name": "Node tốc độ gió",
    "category": "wind",
    "channels": [
      {"key": "wind_speed", "label": "Tốc độ gió", "unit": "m/s",
       "fc": 4, "address": 1, "type": "int16", "scale": 0.1,
       "min": 0, "max": 60, "display_min": 0, "display_max": 15,
       "invalid_value": -32768}
    ]
  },
  {
    "name": "Node nhiệt ẩm, ánh sáng",
    "category": "climate",
    "channels": [
      {"key": "temperature", "label": "Nhiệt độ", "unit": "°C",
       "fc": 4, "address": 0, "type": "float32", "byte_order": "ABCD",
       "min": -40, "max": 80, "display_min": 0, "display_max": 50},
      {"key": "humidity", "label": "Độ ẩm", "unit": "%RH",
       "fc": 4, "address": 2, "type": "float32", "byte_order": "ABCD",
       "min": 0, "max": 100, "display_min": 0, "display_max": 100},
      {"key": "illuminance", "label": "Ánh sáng", "unit": "lux",
       "fc": 4, "address": 4, "type": "float32", "byte_order": "ABCD",
       "min": 0, "max": 200000, "display_min": 0, "display_max": 100000}
    ]
  },
  {
    "name": "Node CO2 (MQ135)",
    "category": "climate",
    "channels": [
      {"key": "co2", "label": "CO2", "unit": "ppm",
       "fc": 4, "address": 0, "type": "float32", "byte_order": "ABCD",
       "min": 0, "max": 10000, "display_min": 0, "display_max": 2000,
       "estimate": true}
    ]
  }
]
```

Hệ số 0.1 của tốc độ gió đã chốt (đọc 86 là 8,6 m/s); các giới hạn và thang hiển thị là giá trị tạm, chỉnh theo firmware, datasheet cảm biến và điều kiện nhà kính. `min`, `max` là phạm vi hợp lệ, quyết định cờ `out_of_range`; `display_min`, `display_max` là thang hiển thị mặc định, chỉ ảnh hưởng giao diện. Ví dụ thang nhiệt độ mặc định 0 đến 50 °C, còn nhà kính khu A đặt riêng 10 đến 40 °C để thanh dải đo dễ đọc hơn.

## 5. Collector: thu thập dữ liệu

Mỗi kết nối có một worker riêng và gửi request tuần tự; một cảm biến hỏng không được làm chậm các cảm biến khác trên cùng bus.

### Lập lịch

- Worker là một asyncio task; các kết nối khác nhau chạy song song.
- Worker chọn thiết bị đến hạn tiếp theo, theo chu kỳ riêng của từng thiết bị.
- Gộp thanh ghi: các kênh cùng function code, cách nhau không quá 4 thanh ghi, được đọc trong một request, tối đa 125 thanh ghi (giới hạn của FC 03/04).
- Một vòng đọc kéo dài hơn chu kỳ cấu hình thì ghi cảnh báo bus quá tải vào chẩn đoán, thay vì âm thầm trễ.

Ngân sách thời gian ở 9600 baud: một lần đọc 2 thanh ghi tốn khoảng 25 ms trên dây, cộng thời gian phản hồi của cảm biến, thường 20 đến 200 ms. 10 thiết bị đọc xong trong dưới 2,5 giây, nên chu kỳ 10 giây còn dư nhiều.

### Xử lý lỗi

| Tình huống | Hành vi |
| --- | --- |
| Timeout, lỗi CRC, phản hồi sai định dạng, Modbus exception | Thử lại theo cấu hình kết nối |
| 3 lần đọc thất bại liên tiếp | Thiết bị chuyển `offline`, thử lại với khoảng giãn dần tới 60 giây. Nếu không, mỗi vòng cảm biến hỏng sẽ ăn hết timeout và kéo chậm cả bus |
| Đọc thành công trở lại | Chuyển `online` ngay, ghi sự kiện |
| Mọi lần đọc lỗi | Không ghi bản ghi đo: không lưu 0, không lặp giá trị cũ. Chỉ cập nhật trạng thái, bộ đếm lỗi và bảng sự kiện; biểu đồ tự hiện khoảng trống |

### Giải mã và chất lượng

- Thanh ghi thô, qua kiểu dữ liệu và thứ tự byte, nhân hệ số, cộng offset, rồi kiểm tra phạm vi hợp lệ.
- Mỗi giá trị mang cờ `good` hoặc `out_of_range`. Giá trị `out_of_range` vẫn lưu để điều tra nhưng không vào dữ liệu gộp và không xét ngưỡng.
- Giá trị NaN (float32) hoặc bằng mã lỗi khai báo trong mẫu nghĩa là cảm biến bên trong node hỏng: không lưu bản ghi đo, kênh nhận cờ `sensor_fault` trong `channel_latest`, và ghi một sự kiện mỗi khi trạng thái đổi.
- Timestamp là thời điểm nhận phản hồi, UTC, epoch mili giây.

### Ghi dữ liệu

- Bản ghi gom trong bộ nhớ, commit mỗi 5 giây hoặc khi đủ 500 bản ghi. Mỗi commit là một transaction: thêm vào `readings`, cập nhật `channel_latest` và `device_status`.
- Mất điện đột ngột mất tối đa 5 giây dữ liệu; CSDL không hỏng nhờ WAL.
- Tác vụ gộp chạy sau mỗi cửa sổ 5 phút, và tự bù các cửa sổ còn thiếu khi collector khởi động lại.

### Vận hành

- API nội bộ trên Unix socket `/run/greenhouse/collector.sock`, chỉ group của dịch vụ web truy cập được: `GET /status`, `POST /reload`, `POST /test-read`, `POST /scan`, `POST /set-address`, `POST /frame-log`.
- Khi đang quét hoặc đổi địa chỉ trên một bus, worker của bus đó tạm dừng polling; các bus khác chạy bình thường.
- Một task giám sát báo sống cho systemd watchdog khi mọi worker còn quay vòng lặp (kể cả lúc chờ thử lại); worker treo quá 60 giây thì systemd khởi động lại collector.
- Chẩn đoán báo cảnh báo nếu đồng hồ hệ thống chưa đồng bộ khi bắt đầu ghi.

## 6. Lưu trữ dữ liệu

SQLite đủ cho quy mô này: 10 kênh ở chu kỳ 10 giây chỉ là 1 bản ghi mỗi giây, một file duy nhất dễ backup, không tốn RAM cho server CSDL riêng. Cân nhắc TimescaleDB hoặc InfluxDB khi vượt vài trăm kênh ở chu kỳ 1 giây, hoặc khi nhiều máy cùng ghi.

Thiết lập khi mở kết nối: `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`, `foreign_keys=ON`.

### Schema

| Bảng | Cột chính | Ghi chú |
| --- | --- | --- |
| `users` | id, username, password\_hash, role, is\_active, created\_at, last\_login\_at | role là `admin` hoặc `viewer` |
| `sessions` | token\_hash, user\_id, created\_at, expires\_at, ip | Session phía server, thu hồi được ngay khi khóa user |
| `connections` | id, name, type, params (JSON), enabled | type là `rtu` hoặc `tcp`; params kiểm tra bằng Pydantic theo type |
| `device_templates` | id, name, category, definition (JSON) | Định dạng như ví dụ ở mục 4.4 |
| `devices` | id, name, zone, connection\_id, unit\_id, template\_id, poll\_interval\_s, enabled, deleted\_at | Unique index (connection\_id, unit\_id) có điều kiện `deleted_at IS NULL` |
| `channels` | id, device\_id, key, label, unit, display\_min, display\_max, alarm\_low, alarm\_high, enabled | Sinh từ mẫu khi tạo thiết bị; id ổn định để gắn dữ liệu. display\_min, display\_max để NULL thì dùng thang mặc định của mẫu |
| `readings` | channel\_id, ts, value, quality | PRIMARY KEY (channel\_id, ts), WITHOUT ROWID |
| `readings_5m` | channel\_id, ts, avg, min, max, count, sin\_avg, cos\_avg | Gộp 5 phút từ giá trị `good`; sin\_avg, cos\_avg chỉ dùng cho kênh `circular_mean` để gộp tiếp chính xác |
| `channel_latest` | channel\_id, ts, value, quality | Nguồn cho màn hình realtime |
| `device_status` | device\_id, state, last\_ok\_ts, last\_error, consecutive\_failures, counters (JSON) | Bộ đếm request, timeout, CRC, exception, thời gian phản hồi |
| `device_events` | id, device\_id, ts, type, detail | online, offline, lỗi |
| `audit_log` | id, ts, user\_id, action, entity, entity\_id, before, after |  |
| `settings` | key, value | Tên site, múi giờ, thời gian lưu giữ, lịch backup; màn hình HMI: hmi\_layout, hmi\_cards (thẻ và thứ tự), hmi\_allow\_charts |

### Lưu giữ và truy vấn

- `readings` (dữ liệu thô): mặc định giữ 365 ngày, admin chỉnh được.
- `readings_5m`: giữ vĩnh viễn.
- Truy vấn biểu đồ: server chọn bucket sao cho mỗi kênh trả về tối đa khoảng 2.000 điểm. Bucket dưới 5 phút đọc từ `readings`; từ 5 phút trở lên gộp từ `readings_5m`. Mỗi bucket trả về avg, min, max để biểu đồ vẽ dải dao động.

Với quy tắc này, truy vấn từ bảng thô không bao giờ quét quá khoảng 7 ngày dữ liệu mỗi kênh, nên biểu đồ nhiều tháng vẫn nhanh trên Pi. Ước lượng với 10 kênh, chu kỳ 10 giây: 86.400 bản ghi/ngày, khoảng 30 byte mỗi bản ghi, tức khoảng 1 GB/năm cho dữ liệu thô; `readings_5m` khoảng 50 MB/năm.

### Backup và chuẩn bị cho cloud

- Backup hằng ngày lúc 2 giờ sáng bằng `VACUUM INTO` sang ổ khác hoặc USB, giữ 7 bản gần nhất; admin tải được bản mới nhất.
- Giai đoạn sau, một dịch vụ `sync` đọc `readings` theo con trỏ (timestamp cuối đã gửi thành công của từng kênh) và đẩy theo lô qua MQTT hoặc HTTPS. Mất Internet nhiều ngày không mất dữ liệu, miễn thời gian lưu dữ liệu thô dài hơn lần mất mạng dài nhất. Giai đoạn này không cần làm gì thêm.

## 7. Hiển thị thông số đo

Dành cho cả `viewer` và `admin`. Màn HDMI cắm vào Pi hiển thị bản HMI chỉ xem (cuối mục này); tablet và điện thoại đăng nhập như trình duyệt thường. Giao diện tiếng Việt, dùng tốt trên điện thoại vì người vận hành thường xem ngay trong nhà kính.

### Trang tổng quan

- Thẻ giá trị nhóm theo khu vực. Mỗi thẻ: tên kênh, giá trị, đơn vị, thời điểm cập nhật, đường xu hướng 1 giờ.
- Cập nhật qua SSE; độ trễ tối đa khoảng 7 giây (commit 5 giây cộng chu kỳ đẩy 2 giây).
- Trạng thái mỗi thẻ phân biệt bằng cả màu và biểu tượng:

| Trạng thái | Điều kiện |
| --- | --- |
| Bình thường | Giá trị `good`, trong ngưỡng |
| Vượt ngưỡng | Ngoài `alarm_low` hoặc `alarm_high` của kênh |
| Dữ liệu cũ | Không có giá trị mới sau 3 lần chu kỳ đọc |
| Lỗi cảm biến | Node vẫn trả lời nhưng báo cảm biến bên trong hỏng (`sensor_fault`) |
| Mất kết nối | Thiết bị `offline` |

### Biểu đồ lịch sử

- Chọn một hoặc nhiều kênh; khoảng nhanh 1 giờ, 24 giờ, 7 ngày, 30 ngày, hoặc tùy chọn.
- Tối đa 2 trục Y theo đơn vị, ví dụ °C và %RH trên cùng biểu đồ.
- Dữ liệu đã gộp hiện đường avg kèm dải min-max. Khoảng mất dữ liệu (dài hơn 3 lần chu kỳ, hoặc bucket rỗng) hiện là đứt đoạn, không nối thẳng.

### Xuất CSV

- Chọn kênh, khoảng thời gian và độ phân giải: thô, 5 phút, 1 giờ hoặc 1 ngày.
- Dữ liệu thô xuất dạng dài (timestamp, kênh, giá trị, chất lượng) vì mỗi thiết bị được đọc ở thời điểm khác nhau. Dữ liệu gộp xuất dạng rộng, mỗi kênh một cột, thẳng hàng theo bucket.
- Timestamp ISO 8601 kèm múi giờ; dấu chấm thập phân, dấu phẩy phân cách; UTF-8 có BOM để Excel hiển thị đúng tiếng Việt.
- Xuất theo luồng (streaming), không nạp cả tập dữ liệu vào RAM.

### Bản đồ trại

Trang `/ban-do` hiện vị trí trại trên nền bản đồ lưu ngay trên Pi, cho cả viewer và admin; màn HMI không có trang này. Tọa độ do admin nhập, file bản đồ cài khi triển khai. Chi tiết ở [docs/spec-ban-do.md](docs/spec-ban-do.md).

### Màn hình HMI trên Pi

Màn HDMI cắm thẳng vào Pi hiển thị trang `/hmi` do `web` phục vụ trên cổng riêng `127.0.0.1:8081`, chỉ nghe trên loopback (mục 3). Trang chỉ xem và không cần đăng nhập vì chỉ mở được từ chính Pi. Tablet và điện thoại vào `https://[địa chỉ Pi]` qua Caddy và đăng nhập như bình thường để xem và cấu hình.

- Bố cục mặc định là HMI thẻ lớn: mỗi kênh một thẻ với số cỡ lớn, thanh dải đo, xu hướng 1 giờ, giá trị thấp và cao trong 1 giờ; thêm thẻ Hệ thống có đồng hồ, số cảnh báo, trạng thái collector và từng node. Admin chọn bố cục (HMI thẻ lớn hoặc Tổng quan), thẻ nào hiện và theo thứ tự nào (mục 8.7). Mặc định 6 thẻ trên lưới 3 × 2: nhiệt độ, độ ẩm, CO2, ánh sáng, tốc độ gió, hệ thống; bật thêm VPD thì lưới chuyển 4 × 2 (7 đến 8 thẻ). Cỡ chữ số tính theo chiều cao màn. Kênh có cờ ước tính (CO2 từ MQ135) hiện nhãn Ước tính trên thẻ.
- Thanh dải đo vẽ theo thang hiển thị của kênh (mục 4.3): vùng ngoài ngưỡng tô màu nhạt, vạch đậm là giá trị hiện tại. Giá trị ngoài thang thì vạch dừng ở mép kèm mũi tên, con số vẫn hiện đúng. VPD dùng thang cố định 0 đến 2,5 kPa.
- Màu theo tinh thần ISA-101: nền xám trung tính, chỉ dùng màu khi bất thường, để kênh vượt ngưỡng nổi bật khi nhìn từ xa. Trạng thái thẻ theo đúng bảng ở trang tổng quan.
- Chỉ đọc: không có mục quản trị, không đăng nhập, không xuất CSV; biểu đồ lịch sử chỉ hiện khi admin cho phép và màn có cảm ứng. Thanh điều hướng thu gọn thành rail; ngăn kéo hiện địa chỉ web app kèm mã QR để mở nhanh trên điện thoại.
- Chạy không cần người trông: tự kết nối lại SSE, báo Mất kết nối tới Datalogger khi quá 30 giây không có dữ liệu, tự tải lại khi frontend có phiên bản mới hoặc khi admin bấm Tải lại màn hình HMI.
- Lúc Pi vừa khởi động: hiện Đang chờ dữ liệu cho tới khi collector ghi lần đầu, không hiện ô trống hay số 0. Giá trị quá 3 chu kỳ đọc không được cập nhật chuyển sang trạng thái Dữ liệu cũ như trang tổng quan, không đứng yên như thể vẫn đang cập nhật.

### Chỉ số dẫn xuất (ưu tiên thấp)

Tính lúc truy vấn, không lưu. VPD (kPa) từ nhiệt độ T (°C) và độ ẩm RH (%) của cùng một thiết bị:

```latex
\mathrm{SVP} = 0.6108\, e^{\frac{17.27\,T}{T + 237.3}}, \qquad \mathrm{VPD} = \mathrm{SVP}\left(1 - \frac{RH}{100}\right)
```

DLI (mol/m²/ngày), nếu cảm biến ánh sáng đo PAR: tổng PPFD (µmol/m²/s) nhân thời gian (s) trong ngày, chia 1.000.000. Cảm biến đang dùng đo lux, nên DLI chỉ là ước lượng, sai số tùy nguồn sáng (mặt trời hay đèn).

## 8. Admin dashboard

Chỉ dành cho `admin`. Mọi thay đổi cấu hình áp dụng trong vài giây, không khởi động lại dịch vụ, và được ghi vào audit log.

### 8.1 Người dùng

- Danh sách, thêm, sửa vai trò, đặt lại mật khẩu, khóa và mở khóa. Không xóa cứng, để giữ lịch sử audit.
- Khóa user hoặc đổi mật khẩu thì thu hồi mọi session của user đó ngay.
- Không cho khóa hoặc hạ quyền admin cuối cùng còn hoạt động.
- Mật khẩu tối thiểu 10 ký tự. Không có tài khoản mặc định: admin đầu tiên tạo bằng lệnh CLI lúc cài đặt.

### 8.2 Kết nối

- Thêm, sửa, xóa kết nối RTU và TCP theo các trường ở mục 4.1 và 4.2.
- Cổng serial chọn từ danh sách phát hiện được, kèm nhà sản xuất và số serial của adapter.
- Nút Kiểm tra chạy qua collector: TCP mở socket tới host:port; RTU mở cổng với tham số đã nhập.
- Mỗi kết nối hiện số thiết bị, trạng thái worker và thời gian vòng đọc gần nhất.

### 8.3 Mẫu thiết bị

- Thêm, sửa, sao chép từ mẫu có sẵn, import và export JSON.
- Form bảng thanh ghi hiện gợi ý quy đổi địa chỉ (mục 4.4), chặn kiểu 32 bit thiếu thứ tự byte, và cảnh báo khi 2 kênh chồng lấn thanh ghi.
- Mỗi kênh có 2 cặp giới hạn khác nhau: phạm vi hợp lệ (gắn cờ `out_of_range`) và thang hiển thị mặc định (thanh dải đo). Form ghi rõ sự khác nhau ngay dưới 2 cặp ô.

### 8.4 Thiết bị

- Thêm, sửa, xóa; chọn kết nối, unit ID, mẫu, khu vực, chu kỳ đọc; chỉnh nhãn, thang hiển thị và ngưỡng cảnh báo từng kênh, có thanh xem trước vẽ giống trên HMI; kiểm tra theo mục 4.3. Ô thang để trống hiện thang mặc định của mẫu dạng chữ mờ.
- Nút Đọc thử chạy được trước khi lưu, hiện thanh ghi thô (hex), giá trị đã giải mã và thời gian phản hồi, hoặc lỗi cụ thể. Exception hiện kèm tên và gợi ý; ví dụ exception 02 (Illegal Data Address) thường do sai địa chỉ thanh ghi hoặc sai function code.
- Xóa thiết bị là xóa mềm: ẩn khỏi danh sách, dữ liệu lịch sử giữ nguyên.

### 8.5 Commissioning (RTU)

- Quét địa chỉ: chọn bus và dải ID (mặc định 1 đến 247), chạy nền, có tiến độ và nút dừng. Với timeout 200 ms, quét hết dải mất khoảng 1 phút cho mỗi baud rate. Polling trên bus đó tạm dừng trong lúc quét.
- Đổi địa chỉ hoặc baud rate cảm biến: chỉ khi mẫu có khai báo thanh ghi tương ứng. Giao diện bắt xác nhận và nhắc chỉ để một cảm biến mang địa chỉ mặc định trên bus, tránh 2 con cùng trả lời.
- Sau khi ghi, tự đọc lại ở địa chỉ mới để xác nhận. Một số model cần tắt bật nguồn mới nhận baud rate mới.

### 8.6 Chẩn đoán

- Bảng trạng thái từng thiết bị: online hay offline, lần đọc tốt gần nhất, tỷ lệ lỗi 1 giờ và 24 giờ, thời gian phản hồi trung bình, lỗi gần nhất.
- Bộ đếm theo loại lỗi, kèm nguyên nhân hay gặp để người lắp đặt dò lỗi:

| Loại lỗi | Nguyên nhân thường gặp |
| --- | --- |
| Timeout | Sai unit ID, sai baud rate, đấu ngược A/B, đứt dây, cảm biến mất nguồn |
| CRC | Nhiễu, thiếu điện trở đầu cuối, sai parity, 2 thiết bị trùng địa chỉ |
| Exception | Sai địa chỉ thanh ghi hoặc function code |

- Log frame thô (hex, có timestamp) bật theo từng kết nối, tự tắt sau 10 phút để không làm đầy ổ.
- Trạng thái hệ thống: collector online hay offline, dung lượng ổ còn trống, nhiệt độ CPU, đồng hồ đã đồng bộ hay chưa.

### 8.7 Cài đặt, màn hình HMI và nhật ký

- Tên site, tọa độ trại, múi giờ hiển thị (mặc định Asia/Ho\_Chi\_Minh), thời gian lưu dữ liệu thô, lịch backup, tải bản backup.
- Audit log: ai, lúc nào, đổi gì (giá trị trước và sau); lọc theo user và đối tượng.
- Màn hình HMI: trạng thái (đang hiển thị hay không, độ phân giải, kết nối từ lúc nào, lấy từ kết nối SSE của trang HMI); chọn bố cục HMI thẻ lớn hoặc Tổng quan; chọn thẻ hiện trên HMI và thứ tự; cho xem biểu đồ lịch sử trên HMI. Thay đổi áp dụng ngay qua SSE, không cần tải lại.
- Nút Tải lại màn hình HMI gửi sự kiện reload tới trang HMI, dùng khi màn hiển thị bất thường mà không cần ra tận Pi. Mã QR trên ngăn kéo HMI sinh ở frontend từ địa chỉ LAN của Pi, không gọi dịch vụ ngoài.

## 9. API

REST trả JSON, tiền tố `/api`, xác thực bằng session cookie; luồng realtime dùng SSE trên cùng cookie. Cột Quyền ghi vai trò thấp nhất được gọi.

| Nhóm | Endpoint | Quyền |
| --- | --- | --- |
| Xác thực | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | công khai, đã đăng nhập |
| Dữ liệu | `GET /overview`: giá trị mới nhất và trạng thái mọi thiết bị | viewer |
| Dữ liệu | `GET /stream`: SSE, sự kiện `reading` và `device_status` | viewer |
| Dữ liệu | `GET /readings?channels=1,2&from=&to=&max_points=2000` | viewer |
| Dữ liệu | `GET /export.csv?channels=&from=&to=&resolution=`, resolution là raw, 5m, 1h hoặc 1d | viewer |
| Dữ liệu | `GET /devices`, `GET /channels` (chỉ đọc) | viewer |
| Bản đồ | `GET /map/config`, `GET /map/basemap.pmtiles` (đọc theo Range). Không có trên cổng HMI | viewer |
| HMI | `GET /hmi/overview`, `GET /hmi/stream`; `GET /hmi/readings` khi admin cho xem biểu đồ. Chỉ có trên cổng 127.0.0.1:8081 | không cần đăng nhập, chỉ từ chính Pi |
| Người dùng | `GET, POST /admin/users`; `PATCH /admin/users/{id}`; `POST /admin/users/{id}/reset-password` | admin |
| Kết nối | `GET, POST /admin/connections`; `GET, PATCH, DELETE /admin/connections/{id}`; `POST /admin/connections/{id}/test`; `GET /admin/serial-ports` | admin |
| Mẫu | `GET, POST /admin/templates`; `GET, PATCH, DELETE /admin/templates/{id}`; `POST /admin/templates/import` | admin |
| Thiết bị | `GET, POST /admin/devices`; `GET, PATCH, DELETE /admin/devices/{id}`; `POST /admin/devices/test-read` nhận cấu hình chưa lưu | admin |
| Commissioning | `POST /admin/connections/{id}/scan` trả job id; `GET /admin/jobs/{id}`; `POST /admin/connections/{id}/set-address` | admin |
| Chẩn đoán | `GET /admin/diagnostics`; `GET, POST /admin/connections/{id}/frame-log` | admin |
| Hệ thống | `GET, PUT /admin/settings`; `GET /admin/audit-log`; `POST /admin/backup` | admin |
| Màn hình HMI | `GET, PUT /admin/hmi`; `POST /admin/hmi/reload` | admin |

Quy ước:

- Lỗi trả về `{"error": {"code": "duplicate_unit_id", "message": "...", "field": "unit_id"}}` với mã HTTP chuẩn: 400 dữ liệu sai, 401, 403, 404, 409 khi trùng unit ID hoặc xóa đối tượng đang được dùng.
- Thời gian trong API là epoch mili giây UTC; frontend đổi sang múi giờ hiển thị.
- Không xóa được kết nối hoặc mẫu còn thiết bị dùng (409).
- Request ghi (POST, PATCH, PUT, DELETE) phải kèm header `X-CSRF-Token` khớp với token của session.
- Trang tài liệu OpenAPI của FastAPI chỉ mở cho admin.
- API nội bộ của collector nằm trên Unix socket (mục 5), không lộ ra mạng.
- Cổng `127.0.0.1:8081` chỉ phục vụ trang HMI và các endpoint `/hmi/...` chỉ đọc; Caddy không chuyển tiếp tới cổng này nên từ mạng không gọi được. Endpoint quản trị không có trên cổng này.

## 10. Yêu cầu phi chức năng

Hệ thống phải chạy đủ chức năng khi không có Internet và chịu được mất điện đột ngột.

| Nhóm | Yêu cầu |
| --- | --- |
| Hiệu năng | Trang tổng quan tải dưới 2 giây trong LAN; biểu đồ 30 ngày của 4 kênh dưới 2 giây trên Pi 4; tổng RAM hai dịch vụ dưới 300 MB |
| Độ tin cậy | systemd `Restart=always` cho cả 2 dịch vụ; watchdog cho collector; bật hardware watchdog của Pi; mất điện không làm hỏng CSDL, mất tối đa 5 giây dữ liệu |
| Chạy offline | Mọi chức năng chạy khi không có Internet; frontend không tải gì từ CDN |
| Thời gian | Lưu UTC, hiển thị theo múi giờ cấu hình; chrony đồng bộ NTP khi có mạng; RTC bắt buộc |
| Truy cập | Chỉ trong LAN; từ xa qua VPN (WireGuard hoặc Tailscale), không mở port ra Internet; HTTPS qua Caddy với chứng chỉ nội bộ |
| Màn hình HMI | Cổng 8081 chỉ nghe trên 127.0.0.1 và chỉ có endpoint chỉ đọc. Không token, không mật khẩu: người đứng trước màn vốn đã thấy số liệu. HTTP thường là đủ vì trình duyệt coi localhost là ngữ cảnh an toàn. Không nhận diện HMI bằng IP nguồn: mọi request đi qua Caddy cũng đến từ 127.0.0.1, nên phân biệt bằng cổng, không bằng địa chỉ. |
| Bảo mật dịch vụ | Chạy bằng user riêng, không phải root; chỉ collector thuộc group `dialout`; Unix socket của collector chỉ group của web truy cập |
| Đăng nhập | Cookie `HttpOnly`, `Secure`, `SameSite=Lax`; session hết hạn sau 7 ngày không hoạt động; tối đa 5 lần sai mỗi 10 phút cho mỗi IP |
| Bảo trì | Log qua journald; migration CSDL đánh số phiên bản; backup hằng ngày giữ 7 bản |

## 11. Lộ trình và tiêu chí nghiệm thu

Làm theo 4 mốc, kiểm chứng collector trên phần cứng thật trước khi làm giao diện: lỗi bus RS-485 rất khó tách khỏi lỗi phần mềm nếu cả hai cùng mới.

&#91;embedded content: lộ trình · 4 mốc, mỗi mốc một điều kiện qua\]

Mỗi mốc chỉ qua khi đạt điều kiện ghi dưới hình thoi; M4 qua khi đạt đủ các kịch bản dưới đây.

Việc theo từng mốc, ước lượng ngày công và rủi ro nằm ở Kế hoạch thực hiện: web app giám sát nhà kính.

Kịch bản nghiệm thu:

- [ ] Rút cáp một cảm biến: thiết bị chuyển `offline` trên giao diện trong vòng 3 chu kỳ; các cảm biến còn lại trên cùng bus vẫn cập nhật đúng chu kỳ.
- [ ] Cắm lại cáp: thiết bị `online` trở lại trong vòng 60 giây.
- [ ] Khởi động lại dịch vụ web trong lúc đang ghi: không có khoảng trống dữ liệu.
- [ ] Cắt điện Pi đột ngột 10 lần: CSDL mở được, `PRAGMA integrity_check` trả về `ok`.
- [ ] Đổi unit ID một thiết bị trên giao diện: áp dụng trong 5 giây, không khởi động lại dịch vụ.
- [ ] Khởi động Pi khi không có mạng: timestamp dữ liệu đúng.
- [ ] Lưu 2 thiết bị cùng unit ID trên một kết nối: bị chặn với mã 409.
- [ ] Cắt điện rồi cấp lại: màn HMI tự hiện số liệu sau khi Pi khởi động, không cần chuột hay bàn phím.
- [ ] Từ máy khác trong LAN: cổng 8081 không kết nối được, và /hmi qua Caddy trả 404.
- [ ] Dừng dịch vụ web 1 phút: HMI báo Mất kết nối tới Datalogger, rồi tự hồi phục khi web chạy lại, không cần thao tác.

## 12. Giả định và câu hỏi mở

Các con số về thời gian bus, dung lượng và hiệu năng ở trên dựa trên những giả định sau; sai giả định nào thì xem lại mục liên quan.

- Quy mô: 1 Pi, tối đa khoảng 20 thiết bị và 60 kênh, chu kỳ đọc từ 1 giây trở lên (mục 5, 6).
- 1 đến 2 bus RS-485, cộng một số thiết bị hoặc gateway Modbus TCP (mục 4).
- Node 01, 02 và 03 chạy firmware do nhóm tự viết, nên bảng thanh ghi và quy ước mã lỗi còn chỉnh được (mục 4.5).
- Người dùng truy cập qua LAN của trang trại, dưới 10 người cùng lúc (mục 10).
- Màn HMI là màn HDMI 10 inch 1280 × 800 cắm thẳng vào Pi, giả định có cảm ứng USB; tablet và điện thoại truy cập Pi qua LAN để xem và cấu hình (mục 3, 7).

Câu hỏi mở:

- [x] Bảng thanh ghi Node 01 (tốc độ gió) và Node 02 (nhiệt ẩm, ánh sáng): đã chốt, xem mục 4.5.
- [x] CO2: Node 03, input register 0, float32, cảm biến MQ135 (mục 4.5).
- [x] Node 01: địa chỉ 1, hệ số 0,1 (đọc 86 là 8,6 m/s).
- [x] Thứ tự word float32: ABCD.
- [x] Bus: 9600 8N1.
- [x] Ánh sáng đo lux; DLI chỉ là ước lượng.
- [ ] Cảm biến gió đặt trong hay ngoài nhà kính? Ngoài trời thì cần chống sét cho đường RS-485.
- [x] Màn hình cố định tại nhà kính: màn HDMI cắm vào Pi, Chromium kiosk mở trang HMI qua localhost (mục 3, 7).
- [ ] Màn HDMI 10 inch 1280 × 800 đã chốt; còn chờ: màn có cảm ứng không? Không cảm ứng thì HMI chỉ hiện trang thẻ, bỏ ngăn kéo và biểu đồ.
- [ ] Thay MQ135 bằng cảm biến CO2 NDIR (ví dụ Senseair S8)? Giữ input register 0 kiểu float32 thì web app không đổi (mục 4.5).
- [ ] Có cần truy cập từ xa trước khi làm phần cloud không?

## Nguồn

- [pymodbus trên PyPI](https://pypi.org/project/pymodbus/): phiên bản 3.15.0, quy ước đánh số phiên bản, các kiểu frame hỗ trợ (truy cập 27/09/2026).
- [MQ135, trang sản phẩm của Winsen](https://www.winsen-sensor.com/sensors/voc-sensor/mq135.html): khí đích, thời gian làm nóng trên 48 giờ (truy cập 29/09/2026).
- [SEN-MQ135, datasheet của Joy-IT](https://joy-it.net/files/files/Produkte/SEN-MQ135/SEN-MQ135_Datasheet_2023-09-26.pdf): khí đích, tương quan giữa điện trở cảm biến với nhiệt độ, độ ẩm (truy cập 29/09/2026).
- [SenseAir S8 Residential, datasheet](http://co2meters.com/Documentation/Manuals/DS_SE_0119_CM_0177_Revised8.pdf): NDIR, UART theo giao thức Modbus, cơ chế ABC giả định không khí ngoài trời khoảng 400 ppm (truy cập 29/09/2026).

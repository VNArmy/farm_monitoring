# Tài liệu dự án giám sát nhà kính

Bản mới nhất luôn nằm trong các tài liệu dưới đây; file này chỉ để tìm nhanh.

- Spec web app trên Raspberry Pi: https://claude.ai/artifact/Mty9SnPGivnHb3mFgm84dc
- Bản thiết kế giao diện (canvas, gồm HMI và trang admin): https://claude.ai/artifact/Eoxoi2rZTAJiznVtCjuRpe
- Kế hoạch thực hiện (M0 đến M4, khoảng 51 ngày công): https://claude.ai/artifact/1mmRCK8Pwms6VSyf4tZGD7
- Spec hiển thị vị trí trại trên bản đồ: [docs/spec-ban-do.md](docs/spec-ban-do.md)
- Plan thực hiện trang Bản đồ: [docs/plan-ban-do.md](docs/plan-ban-do.md)
- Mockup trang Bản đồ và luồng đặt vị trí trại (mở bằng trình duyệt): [docs/mockup-ban-do.html](docs/mockup-ban-do.html)

## Quyết định đã chốt

- Pi 4 hoặc Pi 5 bản 4 GB, chạy 3 process: collector (duy nhất chạm bus Modbus), web (FastAPI sau Caddy), hmi (cage + Chromium kiosk).
- Bus RS-485 9600 8N1; mọi node dùng input register (FC 04), địa chỉ giao thức tính từ 0, float32 thứ tự word ABCD (29/09/2026).
- Node 01 tốc độ gió: unit ID 1, int16, input register 1, hệ số 0,1 (đọc 86 là 8,6 m/s).
- Node 02 nhiệt độ, độ ẩm, ánh sáng (lux): unit ID 2, float32 ở input register 0, 2, 4.
- Node 03 CO2: unit ID 3, float32 ở input register 0, cảm biến MQ135; spec coi kênh này là ước tính cho tới khi thay bằng cảm biến NDIR.
- Màn HMI là màn HDMI 10 inch 1280 × 800 cắm thẳng vào Pi, mở http://127.0.0.1:8081/hmi; cổng này chỉ nghe trên loopback nên không cần đăng nhập. Chưa xác nhận màn có cảm ứng.
- Tablet và điện thoại vào https://[địa chỉ Pi] qua Caddy, đăng nhập viewer để xem, admin để cấu hình.
- Thang hiển thị: mặc định theo mẫu thiết bị, ghi đè được cho từng kênh của thiết bị.
- SQLite chế độ WAL; dữ liệu thô giữ 365 ngày, dữ liệu gộp 5 phút giữ vĩnh viễn.
- Tọa độ trại nhập tay ở Quản trị · Cài đặt; để ngỏ phần lấy từ GPS nếu có (05/11/2026).
- Giao diện và hướng dẫn sử dụng gọi máy đặt ở trại là Datalogger, vì sau này có thể không còn là Pi; tài liệu thiết kế và README cài đặt vẫn viết Pi (05/11/2026).

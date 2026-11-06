# Plan: Trang Bản đồ và sửa trang Tài khoản

05/11/2026 · Làm theo [spec-ban-do.md](spec-ban-do.md). Mockup: [mockup-ban-do.html](mockup-ban-do.html).

## Quyết định

- **Tọa độ trại nhập tay** ở Quản trị · Cài đặt, như spec mục 3. Không có nút lấy vị trí, không gọi `navigator.geolocation`.
- **GPS để ngỏ:** chưa viết code. Spec mục 8 ghi nguồn GPS sau này sẽ chỉ điền sẵn ô Tọa độ trại, nên không phải đổi dữ liệu hay API đọc.
- **Từ mockup, lấy:** trang Bản đồ khi có dữ liệu, các trạng thái thiếu dữ liệu, thanh tab 5 mục, lệnh cài file có sẵn khung cắt.
- **Từ mockup, không làm đợt này:** luồng Lấy vị trí, kéo bản đồ để chỉnh ghim, sửa tọa độ trên trang Bản đồ, ngưỡng cảnh báo 100 m và 500 m. Các phần này giữ làm tham khảo khi làm GPS.
- **Chữ người dùng thấy** viết Datalogger, không viết Pi.

## Các bước

| # | Việc | File chính | Xong khi |
| --- | --- | --- | --- |
| 1 | Sửa lỗi trang Tài khoản tràn ngang trên điện thoại: bỏ `style` đặt cứng hai cột, dùng class `.split.w420` nằm trong quy tắc một cột của điện thoại | `AccountPage.vue`, `styles/app.css` | Bề rộng 390 px không tràn, cả admin và viewer |
| 2 | Backend: `site_lat`, `site_lng`, `clear_site_location`; `GET /api/map/config`, `GET /api/map/basemap.pmtiles`; mount `/map`; `/ban-do` trong `SPA_PATHS` | `core/db.py`, `core/config.py`, `routes/admin_system.py`, `routes/map.py`, `web/app.py` | pytest qua, gồm đọc theo Range, 401, 404 ở cổng HMI |
| 3 | Lệnh `greenhouse install-map <file>` | `__main__.py` | pytest qua: file đúng được cài, file sai bị từ chối, file đang dùng giữ nguyên |
| 4 | Thêm thư viện, font, sprite; tạo file bản đồ mẫu; chạy MapLibre dưới CSP hiện tại | `package.json`, `public/map/`, `components/MapView.vue` | Bản build ở cổng 8080 vẽ được nền, Console không có lỗi CSP |
| 5 | Trang Bản đồ với đủ trạng thái; `lib/geo.ts` có test; route, mục điều hướng, icon, thanh tab, CSS | `pages/MapPage.vue`, `lib/geo.ts`, `router.ts`, `lib/nav.ts`, `lib/icons.ts`, `AppShell.vue`, `styles/app.css` | vitest qua; Chrome thấy đúng từng trạng thái ở 1280 và 390 px |
| 6 | Ô Tọa độ trại ở Cài đặt | `pages/admin/SettingsPage.vue` | Đặt, sửa, xóa được; vĩ độ 91 hoặc thiếu kinh độ bị chặn ngay tại ô; audit log ghi trước và sau |
| 7 | Tài liệu: README, `SPEC.md`, hướng dẫn sử dụng (thêm mục Bản đồ, chụp lại ảnh vì thanh tab đổi, in lại PDF), ghi chú trạng thái trong mockup | `app/README.md`, `SPEC.md`, `docs/huong-dan-su-dung/`, `docs/mockup-ban-do.html` | Nội dung khớp app |
| 8 | Chạy danh sách nghiệm thu ở spec mục 7, ghi lại mục nào chưa làm được | | Có báo cáo từng mục |

Bước 2 và 3 không phụ thuộc giao diện nên làm trước. Bước 4 làm trước bước 5 vì rủi ro lớn nhất nằm ở MapLibre chạy dưới CSP.

## Giới hạn

- Không đụng collector, không cần migration, không đổi `Caddyfile`, `install.sh`, `chromium-policy.json`.
- Màn HMI không có bản đồ; cổng 8081 trả 404 cho `/api/map` và `/map`.
- Không commit nếu chưa được yêu cầu.

## Kiểm tra

- `pytest`, `ruff`, `npm run build` (gồm vue-tsc), `npm test`.
- Chrome thật trên bản build ở cổng 8080, dùng file bản đồ mẫu vùng Đà Lạt, Đức Trọng và thư mục dữ liệu tạm.

Chưa làm được trên máy phát triển, phải làm trên Datalogger thật hoặc tại trại:

- Android, iPhone, đường Tailscale.
- Đọc theo Range qua Caddy.
- Rút Internet của router.
- Các mục nghiệm thu với file thật ở spec mục 7.

## Trạng thái

05/11/2026: bước 1 đến 7 đã làm xong. Bước 8 đã chạy trên máy phát triển; các mục đã qua được đánh dấu ở spec mục 7.

Đã kiểm tra trên bản build ở cổng 8080, Chrome trên Windows, thư mục dữ liệu tạm, file bản đồ mẫu vùng Đà Lạt 3,7 MB.

Còn phải làm trên Datalogger thật hoặc tại trại:

- Các mục chưa đánh dấu ở spec mục 7.
- Chạy `pmtiles extract` thật. File mẫu được cắt bằng script riêng theo đặc tả PMTiles, vì môi trường phát triển không cho chạy file `pmtiles.exe` tải về, nên lệnh này và file nó tạo ra chưa được thử với `greenhouse install-map`.

Sửa thêm ngoài plan: trang Kết nối và Quét bus cũng tràn ngang ở bề rộng 390 px, cùng nguyên nhân với trang Tài khoản (`style` đặt cứng số cột).

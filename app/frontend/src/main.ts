// Điểm vào web app: hỏi phiên đăng nhập, dựng router rồi gắn App.
import { createApp } from 'vue';
import App from './App.vue';
import { setUnauthorizedHandler } from './lib/api';
import { loadMe, session } from './lib/session';
import { router } from './router';
import './styles/fonts.css';
import './styles/app.css';

setUnauthorizedHandler(() => {
  // Phiên hết hạn (7 ngày không dùng) hoặc bị thu hồi: về trang đăng nhập, quay lại đúng trang sau khi đăng nhập.
  if (!session.me) return;
  const next = location.pathname + location.search;
  location.assign(next === '/' ? '/dang-nhap' : `/dang-nhap?next=${encodeURIComponent(next)}`);
});

void loadMe().then(() => {
  createApp(App).use(router).mount('#app');
});

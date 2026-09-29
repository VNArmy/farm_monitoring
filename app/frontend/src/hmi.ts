// Điểm vào màn HMI (http://127.0.0.1:8081/hmi): luồng trực tiếp từ /api/hmi/*, tự nối lại, báo mất kết nối sau 30 giây
// im lặng, tự tải lại khi có frontend mới hoặc khi admin bấm Tải lại màn hình HMI (spec mục 7).
import { createApp, defineComponent, h, watch } from 'vue';
import { createRouter, createWebHistory } from 'vue-router';
import HmiApp from './HmiApp.vue';
import { LIVE, createLive } from './lib/live';
import './styles/fonts.css';
import './styles/app.css';

const params = new URLSearchParams(location.search);

/** Màn có cảm ứng không; ?touch=1 hoặc ?touch=0 để ép khi Chromium nhận sai (một số màn USB báo như chuột). */
function detectTouch(): boolean {
  const forced = params.get('touch');
  if (forced === '1') return true;
  if (forced === '0') return false;
  return window.matchMedia('(any-pointer: coarse)').matches || navigator.maxTouchPoints > 0;
}

const Empty = defineComponent({ render: () => h('div') });
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/hmi' },
    { path: '/hmi', component: Empty, meta: { title: 'Tổng quan', nav: 'tong-quan' } },
    { path: '/hmi/bieu-do', component: Empty, meta: { title: 'Biểu đồ', nav: 'bieu-do' } },
    { path: '/:rest(.*)*', redirect: '/hmi' },
  ],
});

let version: string | null = null;
let reloadToken: string | null = null;
let reloading = false;
function reload(): void {
  if (reloading) return;
  reloading = true;
  // Đợi một nhịp để server kịp phục vụ bản mới, rồi tải lại giữ nguyên tham số (?touch=...).
  setTimeout(() => location.reload(), 1500);
}

const live = createLive({
  overviewUrl: '/api/hmi/overview',
  streamUrl: () => `/api/hmi/stream?w=${window.innerWidth}&h=${window.innerHeight}`,
  sparkUrl: '/api/hmi/sparklines',
  lostAfterMs: 30_000,
  silenceMs: 30_000,
  onReload: reload,
  onVersion: (v) => {
    if (version == null) version = v;
    else if (v && v !== version) reload();
  },
});

// Ảnh chụp đầu tiên mang token tải lại; nối lại sau khi mất kết nối mà token đã đổi (admin bấm Tải lại
// trong lúc đó) thì cũng tải lại. Cấu hình thẻ và bố cục đổi qua hmi_config, áp dụng ngay không tải lại.
watch(
  () => live.state.snap?.hmi?.reload_token,
  (token) => {
    if (!token) return;
    if (reloadToken == null) reloadToken = token;
    else if (token !== reloadToken) reload();
  },
);

router.afterEach((to) => {
  document.title = `${to.meta.title ?? 'HMI'} · HMI · Giám sát nhà kính`;
});

const app = createApp(HmiApp, { touch: detectTouch() });
app.provide(LIVE, live);
app.use(router);
app.mount('#app');
live.start();

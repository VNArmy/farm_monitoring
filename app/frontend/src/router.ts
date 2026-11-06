// Đường dẫn của web app (tiếng Việt không dấu, trùng SPA_PATHS ở server).
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';
import { session } from './lib/session';

declare module 'vue-router' {
  interface RouteMeta {
    title?: string;
    nav?: string;
    admin?: boolean;
    public?: boolean;
  }
}

const routes: RouteRecordRaw[] = [
  { path: '/dang-nhap', component: () => import('./pages/LoginPage.vue'), meta: { title: 'Đăng nhập', public: true } },
  { path: '/', component: () => import('./pages/OverviewPage.vue'), meta: { title: 'Tổng quan', nav: 'tong-quan' } },
  { path: '/bieu-do', component: () => import('./pages/ChartsPage.vue'), meta: { title: 'Biểu đồ', nav: 'bieu-do' } },
  { path: '/ban-do', component: () => import('./pages/MapPage.vue'), meta: { title: 'Bản đồ', nav: 'ban-do' } },
  { path: '/tai-khoan', component: () => import('./pages/AccountPage.vue'), meta: { title: 'Tài khoản', nav: 'tai-khoan' } },
  { path: '/quan-tri', redirect: '/quan-tri/ket-noi' },
  {
    path: '/quan-tri/ket-noi',
    component: () => import('./pages/admin/ConnectionsPage.vue'),
    meta: { title: 'Kết nối', nav: 'ket-noi', admin: true },
  },
  {
    path: '/quan-tri/mau',
    component: () => import('./pages/admin/TemplatesPage.vue'),
    meta: { title: 'Mẫu thiết bị', nav: 'mau', admin: true },
  },
  {
    path: '/quan-tri/thiet-bi',
    component: () => import('./pages/admin/DevicesPage.vue'),
    meta: { title: 'Thiết bị', nav: 'thiet-bi', admin: true },
  },
  { path: '/quan-tri/quet', component: () => import('./pages/admin/ScanPage.vue'), meta: { title: 'Quét bus', nav: 'quet', admin: true } },
  {
    path: '/quan-tri/chan-doan',
    component: () => import('./pages/admin/DiagnosticsPage.vue'),
    meta: { title: 'Chẩn đoán', nav: 'chan-doan', admin: true },
  },
  {
    path: '/quan-tri/nguoi-dung',
    component: () => import('./pages/admin/UsersPage.vue'),
    meta: { title: 'Người dùng', nav: 'nguoi-dung', admin: true },
  },
  {
    path: '/quan-tri/cai-dat',
    component: () => import('./pages/admin/SettingsPage.vue'),
    meta: { title: 'Cài đặt', nav: 'cai-dat', admin: true },
  },
  { path: '/:rest(.*)*', component: () => import('./pages/NotFound.vue'), meta: { title: 'Không tìm thấy trang' } },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: (_to, _from, saved) => saved ?? { top: 0 },
});

router.beforeEach((to) => {
  const me = session.me;
  if (!me) {
    if (to.meta.public) return true;
    const next = to.fullPath;
    return next === '/' ? '/dang-nhap' : { path: '/dang-nhap', query: { next } };
  }
  if (to.path === '/dang-nhap') return '/';
  // Đăng nhập bằng mật khẩu tạm: đổi mật khẩu trước khi làm việc khác (spec mục 8.1).
  if (me.user.must_change_password && to.path !== '/tai-khoan') return '/tai-khoan';
  return true;
});

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · Giám sát nhà kính` : 'Giám sát nhà kính';
});

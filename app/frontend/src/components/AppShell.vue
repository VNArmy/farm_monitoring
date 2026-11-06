<script setup lang="ts">
// Khung trang: sidebar (≥ 1024 px), rail và ngăn kéo (600–1023 px), thanh tab dưới (< 600 px), banner cấp trang.
// kiosk: màn HMI có cảm ứng: luôn là rail, ngăn kéo có mã QR mở web app trên điện thoại, không có mục quản trị.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { RouterLink, useRoute } from 'vue-router';
import { fmtTime, initials } from '../lib/format';
import { useLive } from '../lib/live';
import { ADMIN_NAV, type NavItem } from '../lib/nav';
import { ROLE_NAMES, logout, session } from '../lib/session';
import { local } from '../lib/ui';
import Icon from './Icon.vue';
import QrCode from './QrCode.vue';

const props = withDefaults(defineProps<{ nav: NavItem[]; admin?: boolean; kiosk?: boolean; lanUrl?: string }>(), {
  admin: false,
  kiosk: false,
  lanUrl: '',
});

const live = useLive();
const route = useRoute();

const width = ref(window.innerWidth);
const mode = computed(() => (props.kiosk ? 'tablet' : width.value < 600 ? 'phone' : width.value < 1024 ? 'tablet' : 'desktop'));
const pinnedCollapsed = ref(local.get('gh.nav.collapsed', false));
const collapsed = computed(() => (mode.value === 'tablet' ? true : pinnedCollapsed.value));
const overlay = ref(false);
const mini = ref(local.get('gh.tabbar.mini', false));
const barHidden = ref(false);
let lastY = 0;

const active = computed(() => String(route.meta.nav ?? ''));
const title = computed(() => String(route.meta.title ?? ''));
const user = computed(() => session.me?.user ?? null);
const snap = computed(() => live.state.snap);
const col = computed(() => snap.value?.collector ?? null);
const alarmCount = computed(() => snap.value?.alarms.length ?? 0);

const collText = computed(() => (!snap.value ? 'Đang tải…' : col.value?.online ? 'Collector đang chạy' : 'Collector đang dừng'));
const collSub = computed(() => {
  const c = col.value;
  if (!c?.online) return '';
  return c.last_commit_at ? `Ghi lần cuối ${fmtTime(c.last_commit_at)}` : 'Chưa ghi lần nào';
});
const collDot = computed(() => (!snap.value ? 'off' : col.value?.online ? '' : 'err'));
const liveText = computed(() => {
  if (live.lost.value) return 'Đang nối lại…';
  const ts = live.latestTs.value;
  return ts ? `Trực tiếp · ${fmtTime(ts)}` : 'Trực tiếp';
});

function onResize(): void {
  width.value = window.innerWidth;
}
function onScroll(): void {
  if (mode.value !== 'phone') return;
  const y = window.scrollY;
  const down = y > lastY + 6 && y > 80;
  const up = y < lastY - 6;
  if (down || up) {
    barHidden.value = down;
    lastY = y;
  }
}
function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape' && overlay.value) overlay.value = false;
}

function toggleNav(): void {
  if (mode.value === 'desktop') {
    pinnedCollapsed.value = !pinnedCollapsed.value;
    local.set('gh.nav.collapsed', pinnedCollapsed.value);
  } else overlay.value = !overlay.value;
}
function setMini(v: boolean): void {
  mini.value = v;
  local.set('gh.tabbar.mini', v);
}

watch(mode, () => (overlay.value = false));
watch(
  () => route.fullPath,
  () => {
    overlay.value = false;
    barHidden.value = false;
  },
);
watch(
  () => mode.value === 'phone',
  (phone) => document.body.classList.toggle('has-tabbar', phone),
  { immediate: true },
);

onMounted(() => {
  window.addEventListener('resize', onResize);
  window.addEventListener('scroll', onScroll, { passive: true });
  document.addEventListener('keydown', onKey);
});
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize);
  window.removeEventListener('scroll', onScroll);
  document.removeEventListener('keydown', onKey);
  document.body.classList.remove('has-tabbar');
});

const cur = (id: string): 'page' | undefined => (active.value === id ? 'page' : undefined);
const expanded = computed(() => !collapsed.value || overlay.value);
</script>

<template>
  <div class="shell" :class="{ phone: mode === 'phone' }">
    <aside class="nav" :class="{ collapsed, overlay }" aria-label="Thanh điều hướng">
      <div class="nav-panel">
        <div class="nav-brand">
          <div class="logo" title="Giám sát nhà kính"><Icon name="logo" :size="20" /></div>
          <div class="brand-text">
            <div class="brand-name">Giám sát nhà kính</div>
            <div class="brand-sub">{{ snap?.site_name ?? session.me?.site_name ?? '' }}{{ kiosk ? ' · HMI' : '' }}</div>
          </div>
        </div>
        <nav class="nav-list" aria-label="Điều hướng chính">
          <div class="nav-sec">Theo dõi</div>
          <RouterLink v-for="n in nav" :key="n.id" class="nav-link" :to="n.to" :title="n.label" :aria-label="n.label" :aria-current="cur(n.id)">
            <Icon :name="n.icon" :size="20" /><span>{{ n.label }}</span>
          </RouterLink>
          <template v-if="admin">
            <div class="nav-sec admin">Quản trị</div>
            <div class="nav-div" />
            <RouterLink
              v-for="n in ADMIN_NAV"
              :key="n.id"
              class="nav-link"
              :to="n.to"
              :title="n.label"
              :aria-label="n.label"
              :aria-current="cur(n.id)"
            >
              <Icon :name="n.icon" :size="20" /><span>{{ n.label }}</span>
            </RouterLink>
          </template>
        </nav>
        <button
          v-if="!kiosk"
          type="button"
          class="nav-toggle"
          :aria-expanded="expanded"
          :aria-label="expanded ? 'Thu gọn thanh điều hướng' : 'Mở rộng thanh điều hướng'"
          :title="expanded ? 'Thu gọn thanh điều hướng' : 'Mở rộng thanh điều hướng'"
          @click="toggleNav"
        >
          <Icon name="collapse" /><span>Thu gọn</span>
        </button>
        <div class="nav-foot">
          <div class="nav-status full-only">
            <span class="dot" :class="collDot" />
            <div class="col" style="min-width: 0">
              <span class="fs-13 strong nowrap">{{ collText }}</span>
              <span class="small muted tn nowrap">{{ collSub }}</span>
            </div>
          </div>
          <template v-if="kiosk">
            <div class="kiosk-note full-only"><Icon name="eye" /><span>Chỉ xem trên màn hình này</span></div>
            <div v-if="lanUrl" class="qr-box full-only">
              <QrCode :text="lanUrl" />
              <div class="col gap-4" style="min-width: 0">
                <span class="small strong">Xem và cấu hình trên điện thoại</span>
                <span class="mono" style="font-size: 11px; line-height: 15px; color: var(--text-2); overflow-wrap: anywhere">{{ lanUrl }}</span>
              </div>
            </div>
            <span class="mini-only mini-slot" :title="collText"><span class="dot lg" :class="collDot" /></span>
            <span class="mini-only mini-slot" title="Chỉ xem trên màn hình này"><Icon name="eye" /><span class="sr">Chỉ xem trên màn hình này</span></span>
            <button
              type="button"
              class="icon-btn bordered mini-only"
              aria-label="Mở trên điện thoại: hiện địa chỉ và mã QR"
              title="Mở trên điện thoại"
              @click="overlay = !overlay"
            >
              <Icon name="qr" />
            </button>
          </template>
          <template v-else>
            <div class="nav-user full-only">
              <RouterLink to="/tai-khoan" class="avatar" :title="`Tài khoản ${user?.username ?? ''}`">{{ initials(user?.username) }}</RouterLink>
              <div class="col grow">
                <span class="fs-13 strong ellipsis">{{ user?.username }}</span>
                <span class="small muted nowrap">{{ ROLE_NAMES[user?.role ?? ''] ?? '' }}</span>
              </div>
              <button type="button" class="icon-btn" aria-label="Đăng xuất" title="Đăng xuất" @click="logout"><Icon name="logout" /></button>
            </div>
            <span class="mini-only mini-slot" :title="`${collText}${collSub ? ` · ${collSub.toLowerCase()}` : ''}`"
              ><span class="dot lg" :class="collDot"
            /></span>
            <RouterLink class="mini-only avatar" to="/tai-khoan" :title="`${user?.username ?? ''} · ${ROLE_NAMES[user?.role ?? ''] ?? ''}`">{{
              initials(user?.username)
            }}</RouterLink>
            <button type="button" class="icon-btn mini-only" aria-label="Đăng xuất" title="Đăng xuất" @click="logout"><Icon name="logout" /></button>
          </template>
        </div>
      </div>
    </aside>
    <button v-if="overlay" type="button" class="nav-scrim" aria-label="Đóng thanh điều hướng" @click="overlay = false" />

    <header class="mhead">
      <div class="logo"><Icon name="logo" /></div>
      <div class="col grow">
        <h1>{{ title }}</h1>
        <div class="row gap-6 small text-3"><span class="dot" :class="{ off: live.lost.value }" /><span class="tn">{{ liveText }}</span></div>
      </div>
      <RouterLink
        v-if="alarmCount"
        to="/"
        :aria-label="`${alarmCount} kênh vượt ngưỡng`"
        style="height: 44px; display: flex; align-items: center; text-decoration: none"
      >
        <span class="badge warn" style="height: 30px; padding: 0 10px; border-radius: 15px; font-size: 13px; font-weight: 600"
          ><Icon name="warn" :size="15" />{{ alarmCount }}</span
        >
      </RouterLink>
      <RouterLink
        to="/tai-khoan"
        :aria-label="`Tài khoản ${user?.username ?? ''}`"
        style="width: 44px; height: 44px; display: flex; align-items: center; justify-content: center; text-decoration: none"
      >
        <span class="avatar" style="width: 34px; height: 34px; border-radius: 17px">{{ initials(user?.username) }}</span>
      </RouterLink>
    </header>

    <main id="main" class="main">
      <div v-if="live.lost.value || (snap && !col?.online) || col?.clock_warning" class="banners">
        <div v-if="live.lost.value" class="banner info" role="status">
          <Icon name="refresh" :size="20" />
          <div class="body">
            <span class="strong">{{ kiosk ? 'Mất kết nối tới Datalogger.' : 'Mất kết nối trực tiếp tới Datalogger.' }}</span> Đang thử lại; số liệu trên trang
            có thể đã cũ.
          </div>
        </div>
        <div v-if="snap && !col?.online" class="banner danger" role="alert">
          <Icon name="xCircle" :size="20" />
          <div class="body">
            <span class="strong">Collector đang dừng.</span> Không ghi dữ liệu mới; cấu hình vẫn lưu được và áp dụng khi collector chạy lại.
          </div>
          <RouterLink v-if="admin" to="/quan-tri/chan-doan">Chẩn đoán</RouterLink>
        </div>
        <div v-if="col?.online && col.clock_warning" class="banner warn sm" role="status">
          <Icon name="clock" />
          <div class="body">{{ col.clock_warning }}</div>
        </div>
      </div>
      <slot />
    </main>

    <template v-if="mode === 'phone' && !kiosk">
      <nav class="tabbar" :class="{ on: !mini, hide: barHidden }" aria-label="Điều hướng">
        <RouterLink class="tab" to="/" :aria-current="cur('tong-quan')"><Icon name="grid" :size="22" />Tổng quan</RouterLink>
        <RouterLink class="tab" to="/bieu-do" :aria-current="cur('bieu-do')"><Icon name="chart" :size="22" />Biểu đồ</RouterLink>
        <RouterLink class="tab" to="/ban-do" :aria-current="cur('ban-do')"><Icon name="map" :size="22" />Bản đồ</RouterLink>
        <RouterLink class="tab" to="/tai-khoan" :aria-current="cur('tai-khoan')"><Icon name="user" :size="22" />Tài khoản</RouterLink>
        <span class="tab-sep" />
        <button type="button" class="tab shrink" aria-expanded="true" aria-label="Thu nhỏ thanh điều hướng" @click="setMini(true)">
          <Icon name="shrink" :size="22" />Thu nhỏ
        </button>
      </nav>
      <nav class="tabpill" :class="{ on: mini, hide: barHidden }" aria-label="Điều hướng thu nhỏ">
        <RouterLink to="/" aria-label="Tổng quan" :aria-current="cur('tong-quan')"><Icon name="grid" :size="22" /></RouterLink>
        <RouterLink to="/bieu-do" aria-label="Biểu đồ" :aria-current="cur('bieu-do')"><Icon name="chart" :size="22" /></RouterLink>
        <RouterLink to="/ban-do" aria-label="Bản đồ" :aria-current="cur('ban-do')"><Icon name="map" :size="22" /></RouterLink>
        <RouterLink to="/tai-khoan" aria-label="Tài khoản" :aria-current="cur('tai-khoan')"><Icon name="user" :size="22" /></RouterLink>
        <span class="sep" />
        <button type="button" aria-expanded="false" aria-label="Mở rộng thanh điều hướng" @click="setMini(false)">
          <Icon name="expand" :size="22" />
        </button>
      </nav>
    </template>
  </div>
</template>

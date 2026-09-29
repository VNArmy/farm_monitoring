<script setup lang="ts">
// Màn hình HMI trên Pi (spec mục 7): chỉ xem, không đăng nhập, chạy trong Chromium kiosk không người trông.
// Màn có cảm ứng: rail và ngăn kéo có mã QR, xem biểu đồ nếu admin cho phép. Không cảm ứng: chỉ trang thẻ.
import { computed, defineAsyncComponent, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import AppShell from './components/AppShell.vue';
import Icon from './components/Icon.vue';
import UiHost from './components/UiHost.vue';
import { useLive } from './lib/live';
import type { NavItem } from './lib/nav';
import type { HmiConfig } from './lib/types';
import HmiCards from './pages/HmiCards.vue';
import OverviewPage from './pages/OverviewPage.vue';

// Biểu đồ (uPlot) chỉ tải khi mở, để Chromium trên Pi tải ít mã hơn lúc khởi động.
const ChartsPage = defineAsyncComponent(() => import('./pages/ChartsPage.vue'));

const props = defineProps<{ touch: boolean }>();

const live = useLive();
const route = useRoute();
const router = useRouter();

const cfg = computed<HmiConfig | null>(() => live.state.snap?.hmi ?? null);
const charts = computed(() => props.touch && !!cfg.value?.allow_charts);
const onCharts = computed(() => route.path === '/hmi/bieu-do');
// Màn không cảm ứng không cuộn được: luôn dùng bố cục thẻ lớn.
const layout = computed(() => (props.touch ? (cfg.value?.layout ?? 'cards') : 'cards'));
const nav = computed<NavItem[]>(() => {
  const items: NavItem[] = [{ id: 'tong-quan', to: '/hmi', label: 'Tổng quan', icon: 'grid' }];
  if (charts.value) items.push({ id: 'bieu-do', to: '/hmi/bieu-do', label: 'Biểu đồ', icon: 'chart' });
  return items;
});

// Admin tắt biểu đồ trong lúc đang xem: quay về trang thẻ.
watch([onCharts, charts, cfg], ([on, allowed, c]) => {
  if (on && c && !allowed) void router.replace('/hmi');
});

watch(
  () => onCharts.value || layout.value === 'overview',
  (scroll) => document.body.classList.toggle('scroll', scroll),
  { immediate: true },
);
</script>

<template>
  <AppShell v-if="touch" :nav="nav" kiosk :lan-url="cfg?.lan_url ?? ''">
    <div v-if="!cfg" class="loading"><div class="spinner" role="status" aria-label="Đang tải" /></div>
    <ChartsPage v-else-if="onCharts && charts" hmi />
    <OverviewPage v-else-if="layout === 'overview'" :chart-base="charts ? '/hmi/bieu-do' : null" hmi />
    <HmiCards v-else :cfg="cfg" :charts="charts" />
  </AppShell>
  <div v-else class="shell">
    <main class="main">
      <div v-if="live.lost.value" class="banner info" role="status">
        <Icon name="refresh" :size="20" />
        <div class="body"><span class="strong">Mất kết nối tới Pi.</span> Đang thử lại; số liệu trên màn có thể đã cũ.</div>
      </div>
      <div v-else-if="live.state.snap && !live.state.snap.collector.online" class="banner danger" role="alert">
        <Icon name="xCircle" :size="20" />
        <div class="body"><span class="strong">Collector đang dừng.</span> Không có dữ liệu mới.</div>
      </div>
      <div v-if="!cfg" class="loading" style="flex: 1 1 auto"><div class="spinner" role="status" aria-label="Đang tải" /></div>
      <HmiCards v-else :cfg="cfg" :charts="false" />
    </main>
  </div>
  <UiHost />
</template>

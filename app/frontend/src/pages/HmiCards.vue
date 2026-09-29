<script setup lang="ts">
// Bố cục HMI thẻ lớn (spec mục 7): mặc định 6 thẻ trên lưới 3 × 2, bật thêm thẻ thì chuyển 4 × 2.
import { computed } from 'vue';
import HmiCard from '../components/HmiCard.vue';
import SystemCard from '../components/SystemCard.vue';
import { useLive } from '../lib/live';
import type { HmiConfig, Metric } from '../lib/types';

const props = defineProps<{ cfg: HmiConfig; charts: boolean }>();

const live = useLive();
const snap = computed(() => live.state.snap);

const items = computed(() => {
  const s = snap.value;
  if (!s) return [];
  const out: ({ kind: 'system'; id: string } | { kind: 'metric'; id: string; m: Metric })[] = [];
  for (const c of props.cfg.cards) {
    if (!c.visible) continue;
    if (c.id === 'system') out.push({ kind: 'system', id: c.id });
    else if (c.id.startsWith('ch:')) {
      const m = s.channels.find((x) => `ch:${x.id}` === c.id);
      if (m) out.push({ kind: 'metric', id: c.id, m });
    } else {
      const m = s.derived.find((x) => x.id === c.id);
      if (m) out.push({ kind: 'metric', id: c.id, m });
    }
  }
  return out;
});
</script>

<template>
  <div v-if="!snap" class="loading" style="flex: 1 1 auto"><div class="spinner" role="status" aria-label="Đang tải" /></div>
  <div v-else-if="!snap.channels.length" class="empty" style="max-width: 560px">
    <h2>Chưa có thiết bị nào</h2>
    <p>Cấu hình kết nối và thiết bị trên web app: {{ cfg.lan_url }}</p>
  </div>
  <div v-else class="hmi-grid" :class="{ c4: items.length > 6 }" aria-label="Thông số nhà kính">
    <template v-for="it in items" :key="it.id">
      <SystemCard v-if="it.kind === 'system'" :snap="snap" :now="live.state.now" />
      <HmiCard v-else :m="it.m" :spark="live.spark(it.m)" :now="live.state.now" :chart-link="charts && typeof it.m.id === 'number'" />
    </template>
  </div>
</template>

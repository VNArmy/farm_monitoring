<script setup lang="ts">
// Tổng quan (spec mục 7): giá trị mới nhất của mọi kênh, nhóm theo khu vực, cập nhật qua SSE.
// Dùng chung cho web app và bố cục Tổng quan của màn HMI (chartBase = null khi HMI không cho xem biểu đồ).
import { computed } from 'vue';
import { RouterLink } from 'vue-router';
import Icon from '../components/Icon.vue';
import MetricCard from '../components/MetricCard.vue';
import { fmtAuto, fmtHM, fmtNum, fmtTime, shortName } from '../lib/format';
import { useLive } from '../lib/live';
import { isAdmin } from '../lib/session';
import type { Device, Metric } from '../lib/types';

const props = withDefaults(defineProps<{ chartBase?: string | null; hmi?: boolean }>(), { chartBase: '/bieu-do', hmi: false });

const live = useLive();
const snap = computed(() => live.state.snap);
const now = computed(() => live.state.now);
const admin = computed(() => !props.hmi && isAdmin());

const liveText = computed(() => {
  if (live.lost.value) return 'Đang nối lại…';
  const ts = live.latestTs.value;
  return ts ? `Trực tiếp · cập nhật ${fmtTime(ts)}` : 'Trực tiếp';
});

const alarm = computed(() => {
  const alarms = snap.value?.alarms ?? [];
  if (!alarms.length) return null;
  const lines = alarms.map((a) => {
    const kind = a.kind === 'high' ? 'trên ngưỡng cao' : 'dưới ngưỡng thấp';
    return `${a.label} ${a.zone} đang ${fmtNum(a.value, a.decimals)} ${a.unit}, ${kind} ${fmtAuto(a.threshold)} ${a.unit} từ ${fmtHM(a.since)}.`;
  });
  const ids = [...new Set(alarms.map((a) => a.channel_id))].slice(0, 8).join(',');
  return { count: alarms.length, text: lines.join(' '), link: props.chartBase ? `${props.chartBase}?kenh=${ids}&khoang=24h` : null };
});

const zones = computed(() => {
  const s = snap.value;
  if (!s) return [];
  return s.zones.map((z) => {
    const metrics: Metric[] = [];
    for (const id of z.channels) {
      const c = s.channels.find((x) => x.id === id);
      if (c) metrics.push(c);
    }
    for (const d of s.derived) if (d.zone === z.name && z.devices.includes(d.device_id)) metrics.push(d);
    const devs = z.devices.map((id) => s.devices.find((d) => d.id === id)).filter((d): d is Device => !!d);
    const sub = [devs.map((d) => shortName(d.name)).join(', '), z.connections.join(', ')].filter(Boolean).join(' · ');
    return { name: z.name, sub, metrics };
  });
});

const devices = computed(() => snap.value?.devices ?? []);
const online = computed(() => devices.value.filter((d) => d.state === 'online').length);

function devRight(d: Device): string {
  if (d.state === 'online') return d.rtt_ms != null ? `${Math.round(d.rtt_ms)} ms` : '';
  if (d.state === 'offline') return d.since ? `mất kết nối từ ${fmtHM(d.since)}` : 'mất kết nối';
  if (d.state === 'stale') return d.last_ok_at ? `lần cuối ${fmtTime(d.last_ok_at)}` : 'chưa đọc';
  if (d.state === 'disabled') return 'đang tắt';
  return 'chưa có dữ liệu';
}
const devDot = (s: string): string => (s === 'online' ? '' : s === 'offline' ? 'err' : 'off');
</script>

<template>
  <div class="col gap-24">
    <div class="page-head hide-phone">
      <div>
        <h1>Tổng quan</h1>
        <div class="page-sub">Giá trị mới nhất của mọi kênh đo, nhóm theo khu vực</div>
      </div>
      <div class="row wrap">
        <span class="live-pill"><span class="dot" :class="{ off: live.lost.value }" /><span class="tn">{{ liveText }}</span></span>
        <RouterLink v-if="chartBase" class="btn primary" :to="chartBase"><Icon name="chart" />Xem biểu đồ</RouterLink>
      </div>
    </div>

    <div v-if="!snap" class="loading"><div class="spinner" role="status" aria-label="Đang tải" /></div>

    <div v-else-if="!snap.channels.length" class="empty">
      <h2>Chưa có thiết bị nào</h2>
      <p>{{ admin ? 'Thêm kết nối Modbus, rồi thêm thiết bị để bắt đầu thu thập.' : 'Liên hệ quản trị viên để cấu hình.' }}</p>
      <RouterLink v-if="admin" class="btn primary" to="/quan-tri/ket-noi">Thêm kết nối</RouterLink>
    </div>

    <template v-else>
      <div v-if="alarm" id="canh-bao" class="banner warn" role="status">
        <Icon name="warn" :size="20" />
        <div class="body">
          <span class="strong">{{ alarm.count }} kênh vượt ngưỡng.</span> {{ alarm.text }}
        </div>
        <RouterLink v-if="alarm.link" :to="alarm.link">Xem diễn biến</RouterLink>
      </div>

      <section v-for="z in zones" :key="z.name" class="area">
        <div class="area-head">
          <h2>{{ z.name }}</h2>
          <span>{{ z.sub }}</span>
        </div>
        <div class="cq">
          <div class="cards">
            <MetricCard v-for="m in z.metrics" :key="m.id" :m="m" :spark="live.spark(m)" :now="now" :chart-base="chartBase" />
          </div>
        </div>
      </section>

      <section v-if="devices.length" class="dev-strip" aria-label="Thiết bị">
        <span class="strong" style="color: var(--text)"
          >Thiết bị <span class="muted tn" style="font-weight: 400; margin-left: 4px">{{ online }}/{{ devices.length }} trực tuyến</span></span
        >
        <span v-for="d in devices" :key="d.id">
          <span class="row gap-8"><span class="dot" :class="devDot(d.state)" /><span>{{ shortName(d.name) }} · {{ d.zone }}</span></span>
          <span class="tn muted">{{ devRight(d) }}</span>
        </span>
        <RouterLink v-if="admin" to="/quan-tri/chan-doan" class="ml-auto" style="font-weight: 500">Chẩn đoán</RouterLink>
      </section>
    </template>
  </div>
</template>

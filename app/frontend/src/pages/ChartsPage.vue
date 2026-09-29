<script setup lang="ts">
// Biểu đồ lịch sử và xuất CSV (spec mục 7). Dùng chung cho web app và màn HMI (hmi: chỉ xem, không xuất).
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import HistoryChart from '../components/HistoryChart.vue';
import Icon from '../components/Icon.vue';
import Modal from '../components/Modal.vue';
import { api, download, qs } from '../lib/api';
import { uniqueGaps } from '../lib/chartdata';
import { fmtAuto, fmtDMHM, fmtDateTime, fmtNum, fmtTime, fromLocalInput, shortName, toLocalInput } from '../lib/format';
import { useLive } from '../lib/live';
import { alpha, assignColors, darkOf } from '../lib/palette';
import type { Channel, History } from '../lib/types';
import { local, toast } from '../lib/ui';

const props = withDefaults(defineProps<{ hmi?: boolean }>(), { hmi: false });

const RANGES = [
  { id: '1h', label: '1 giờ', ms: 3_600_000 },
  { id: '24h', label: '24 giờ', ms: 86_400_000 },
  { id: '7d', label: '7 ngày', ms: 7 * 86_400_000 },
  { id: '30d', label: '30 ngày', ms: 30 * 86_400_000 },
  { id: 'custom', label: 'Tùy chọn', ms: 0 },
];
const MAX_CHANNELS = 6;
const EXPORT_RES = [
  { id: 'raw', label: 'Dữ liệu thô', note: 'Dạng dài: mỗi dòng một lần đọc gồm thời điểm, kênh, giá trị, chất lượng.' },
  { id: '5m', label: '5 phút', note: 'Dạng rộng: mỗi kênh một cột trung bình, thẳng hàng theo mốc 5 phút.' },
  { id: '1h', label: '1 giờ', note: 'Dạng rộng: mỗi kênh một cột trung bình, thẳng hàng theo mốc 1 giờ.' },
  { id: '1d', label: '1 ngày', note: 'Dạng rộng: mỗi kênh một cột trung bình, thẳng hàng theo ngày.' },
];

const live = useLive();
const route = useRoute();
const router = useRouter();
const base = props.hmi ? '/hmi/bieu-do' : '/bieu-do';
const storeKey = props.hmi ? 'gh.hmi.chart' : 'gh.chart';
const readingsUrl = props.hmi ? '/api/hmi/readings' : '/api/readings';

const catalog = computed<Channel[]>(() => live.state.snap?.channels ?? []);
const chan = (id: number): Channel | undefined => catalog.value.find((c) => c.id === id);

const saved = local.get<{ ids?: number[]; range?: string }>(storeKey, {});
const q = route.query;
const st = reactive({
  ids: String(q.kenh ?? '')
    .split(',')
    .map(Number)
    .filter((n) => Number.isInteger(n) && n > 0)
    .slice(0, MAX_CHANNELS),
  range: String(q.khoang ?? saved.range ?? '24h'),
  from: Number(q.tu) || 0,
  to: Number(q.den) || 0,
  colors: {} as Record<number, string>,
});
if (!st.ids.length && saved.ids?.length) st.ids = saved.ids.slice(0, MAX_CHANNELS);
if (!RANGES.some((r) => r.id === st.range)) st.range = '24h';
if (st.range === 'custom' && !(st.from && st.to && st.to > st.from)) st.range = '24h';
st.colors = assignColors(st.ids, {});

const data = ref<History | null>(null);
const loading = ref(false);
const error = ref('');
const updatedAt = ref(0);
const customFrom = ref('');
const customTo = ref('');

function span(): [number, number] {
  if (st.range === 'custom') return [st.from, st.to];
  const now = Date.now();
  const r = RANGES.find((x) => x.id === st.range) ?? RANGES[1];
  return [now - r.ms, now];
}

function syncUrl(): void {
  const query: Record<string, string> = { kenh: st.ids.join(','), khoang: st.range };
  if (st.range === 'custom') {
    query.tu = String(st.from);
    query.den = String(st.to);
  }
  void router.replace({ path: base, query });
  local.set(storeKey, { ids: st.ids, range: st.range === 'custom' ? '24h' : st.range });
}

let seq = 0;
async function load(): Promise<void> {
  syncUrl();
  if (!st.ids.length) {
    data.value = null;
    return;
  }
  const my = ++seq;
  const [f, t] = span();
  loading.value = true;
  error.value = '';
  try {
    const d = await api.get<History>(`${readingsUrl}?${qs({ channels: st.ids.join(','), from: f, to: t, max_points: 2000 })}`);
    if (my !== seq) return;
    data.value = d;
    updatedAt.value = Date.now();
  } catch (e) {
    if (my !== seq) return;
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    if (my === seq) loading.value = false;
  }
}

function setRange(id: string): void {
  if (id === 'custom' && st.range !== 'custom') {
    const [f, t] = span();
    st.from = f;
    st.to = t;
    customFrom.value = toLocalInput(f);
    customTo.value = toLocalInput(t);
  }
  st.range = id;
  data.value = null;
  void load();
}

function applyCustom(): void {
  const f = fromLocalInput(customFrom.value);
  const t = fromLocalInput(customTo.value);
  if (!f || !t || t <= f) {
    toast('Thời điểm kết thúc phải sau thời điểm bắt đầu', 'err');
    return;
  }
  st.from = f;
  st.to = t;
  data.value = null;
  void load();
}

function removeChannel(id: number): void {
  st.ids = st.ids.filter((x) => x !== id);
  st.colors = assignColors(st.ids, st.colors);
  void load();
}

// --- Thêm kênh -------------------------------------------------------------------------------
const pickerOpen = ref(false);
const chipsEl = ref<HTMLElement>();
const addBtn = ref<HTMLButtonElement>();
const popStyle = ref<Record<string, string>>({});

const units = computed(() => [...new Set(st.ids.map((id) => chan(id)?.unit).filter((u): u is string => u != null))]);
const pickerGroups = computed(() => {
  const s = live.state.snap;
  if (!s) return [];
  return s.zones.map((z) => ({
    name: z.name,
    items: z.channels
      .map((id) => chan(id))
      .filter((c): c is Channel => !!c)
      .map((c) => {
        const chosen = st.ids.includes(c.id);
        const blocked = !chosen && units.value.length >= 2 && !units.value.includes(c.unit);
        return { c, disabled: chosen || blocked, reason: chosen ? 'đã chọn' : blocked ? 'đã đủ 2 đơn vị' : c.unit };
      }),
  }));
});

function openPicker(): void {
  const btn = addBtn.value;
  const box = chipsEl.value;
  if (!btn || !box) return;
  popStyle.value = {
    left: `${Math.max(0, Math.min(btn.offsetLeft, box.clientWidth - 280))}px`,
    top: `${btn.offsetTop + btn.offsetHeight + 6}px`,
  };
  pickerOpen.value = !pickerOpen.value;
}
function pick(id: number): void {
  st.ids.push(id);
  st.colors = assignColors(st.ids, st.colors);
  pickerOpen.value = false;
  void load();
}
function onDocDown(e: MouseEvent): void {
  if (!pickerOpen.value) return;
  const t = e.target as Node;
  if (chipsEl.value?.querySelector('.popover')?.contains(t) || addBtn.value?.contains(t)) return;
  pickerOpen.value = false;
}
function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape' && pickerOpen.value) {
    pickerOpen.value = false;
    addBtn.value?.focus();
  }
}

// --- Chú giải, thống kê ----------------------------------------------------------------------
const agg = computed(() => (data.value?.bucket_ms ?? 0) > 0);
const spanText = computed(() => {
  const [f, t] = span();
  return `${fmtDateTime(f)} – ${fmtDateTime(t)}`;
});
function bucketText(ms: number): string {
  if (!ms) return 'Dữ liệu thô, mỗi điểm là một lần đọc';
  const m = ms / 60_000;
  const txt = m < 60 ? `${m} phút` : m < 1440 ? `${m / 60} giờ` : `${m / 1440} ngày`;
  return `Mỗi điểm là trung bình ${txt}`;
}
const hasPoints = computed(() => !!data.value?.series.some((s) => s.points.length));
const legend = computed(() => {
  const d = data.value;
  if (!d) return [];
  const us = [...new Set(d.series.map((s) => s.unit))];
  const out: { kind: 'ln' | 'band' | 'th' | 'gap'; color: string; text: string }[] = [];
  for (const s of d.series) {
    const side = us.length > 1 ? (us.indexOf(s.unit) === 0 ? ', trục trái' : ', trục phải') : '';
    out.push({ kind: 'ln', color: st.colors[s.channel_id], text: `${s.label} · ${s.zone} (${s.unit}${side})` });
  }
  if (agg.value && d.series.length) out.push({ kind: 'band', color: alpha(st.colors[d.series[0].channel_id] ?? '#999999', 0.22), text: 'Dải thấp nhất – cao nhất' });
  for (const s of d.series) {
    const c = darkOf(st.colors[s.channel_id]);
    if (s.alarm_high != null) out.push({ kind: 'th', color: c, text: `Ngưỡng cao ${s.label.toLowerCase()} ${fmtAuto(s.alarm_high)} ${s.unit}` });
    if (s.alarm_low != null) out.push({ kind: 'th', color: c, text: `Ngưỡng thấp ${s.label.toLowerCase()} ${fmtAuto(s.alarm_low)} ${s.unit}` });
  }
  if (d.series.some((s) => s.gaps.length)) out.push({ kind: 'gap', color: '', text: 'Không có dữ liệu' });
  return out;
});
const stats = computed(() =>
  (data.value?.series ?? [])
    .filter((s) => s.stats)
    .map((s) => {
      const dd = s.decimals ?? 1;
      const x = s.stats as NonNullable<typeof s.stats>;
      return {
        id: s.channel_id,
        label: s.label,
        color: darkOf(st.colors[s.channel_id]),
        text: ` · thấp ${fmtNum(x.min, dd)} · trung bình ${fmtNum(x.avg, dd)} · cao ${fmtNum(x.max, dd)} ${s.unit}`,
      };
    }),
);
const gapNote = computed(() => {
  const gaps = uniqueGaps(data.value?.series ?? []);
  if (!gaps.length) return '';
  const g = gaps[0];
  const more = gaps.length > 1 ? ` (và ${gaps.length - 1} khoảng khác)` : '';
  return `${fmtDMHM(g.from)}–${fmtDMHM(g.to).split(' ').pop()}: ${shortName(g.device)} không có dữ liệu${more}`;
});

// --- Xuất CSV --------------------------------------------------------------------------------
const exp = reactive({ open: false, res: local.get('gh.export.res', '1h'), counts: {} as Record<string, number>, from: 0, to: 0 });
const expNote = computed(() => `${EXPORT_RES.find((r) => r.id === exp.res)?.note ?? ''} UTF-8 có BOM, thời gian ISO 8601 kèm múi giờ của site.`);

async function openExport(): Promise<void> {
  const [f, t] = span();
  exp.from = f;
  exp.to = t;
  exp.counts = {};
  exp.open = true;
  try {
    exp.counts = await api.get<Record<string, number>>(`/api/export/estimate?${qs({ channels: st.ids.join(','), from: f, to: t })}`);
  } catch {
    // không bắt buộc
  }
}
function doExport(): void {
  local.set('gh.export.res', exp.res);
  download(`/api/export.csv?${qs({ channels: st.ids.join(','), from: exp.from, to: exp.to, resolution: exp.res })}`);
  exp.open = false;
  toast('Đang tải tệp CSV');
}

// --- Vòng đời --------------------------------------------------------------------------------
let timer: ReturnType<typeof setInterval> | undefined;
onMounted(() => {
  document.addEventListener('mousedown', onDocDown);
  document.addEventListener('keydown', onKey);
  if (st.range === 'custom') {
    customFrom.value = toLocalInput(st.from);
    customTo.value = toLocalInput(st.to);
  }
  void load();
  // Khoảng tính tới hiện tại thì tự làm mới.
  timer = setInterval(() => {
    if (st.range === '1h' && Date.now() - updatedAt.value > 20_000) void load();
    else if (st.range === '24h' && Date.now() - updatedAt.value > 120_000) void load();
  }, 10_000);
});
onBeforeUnmount(() => {
  clearInterval(timer);
  document.removeEventListener('mousedown', onDocDown);
  document.removeEventListener('keydown', onKey);
});

// Mở trang khi chưa chọn kênh nào: lấy 2 kênh đầu của khu vực đầu tiên khi ảnh chụp tới.
watch(
  () => live.state.snap?.zones,
  (z) => {
    if (!st.ids.length && z?.length && !data.value) {
      st.ids = z[0].channels.slice(0, 2);
      st.colors = assignColors(st.ids, st.colors);
      void load();
    }
  },
  { immediate: true },
);
</script>

<template>
  <div class="col gap-20">
    <div class="page-head">
      <div class="title-block">
        <h1>Biểu đồ</h1>
        <div class="page-sub">
          {{ hmi ? 'Trên màn hình HMI: chọn kênh và khoảng thời gian, không xuất dữ liệu' : 'Lịch sử theo kênh, tối đa 2 trục đơn vị trên một biểu đồ' }}
        </div>
      </div>
      <div class="seg" role="group" aria-label="Khoảng thời gian">
        <button v-for="r in RANGES" :key="r.id" type="button" :aria-pressed="st.range === r.id" @click="setRange(r.id)">{{ r.label }}</button>
      </div>
    </div>

    <div v-if="st.range === 'custom'" class="row wrap gap-12">
      <div class="field"><label for="ch-tu">Từ</label><input id="ch-tu" v-model="customFrom" class="input sm" type="datetime-local" /></div>
      <div class="field"><label for="ch-den">Đến</label><input id="ch-den" v-model="customTo" class="input sm" type="datetime-local" /></div>
      <button type="button" class="btn sm" style="align-self: flex-end" @click="applyCustom">Áp dụng</button>
    </div>

    <div ref="chipsEl" class="row wrap gap-8" style="position: relative">
      <span class="fs-13 text-3" style="font-weight: 500; margin-right: 4px">Kênh</span>
      <template v-for="id in st.ids" :key="id">
        <span v-if="chan(id)" class="chip">
          <span class="sw" :style="{ background: st.colors[id] }" />{{ chan(id)?.label }} · {{ chan(id)?.zone }}
          <button type="button" :aria-label="`Bỏ kênh ${chan(id)?.label} ${chan(id)?.zone}`" @click="removeChannel(id)"><Icon name="x" :size="14" /></button>
        </span>
      </template>
      <button v-if="st.ids.length < MAX_CHANNELS" ref="addBtn" type="button" class="btn-chip" aria-haspopup="true" :aria-expanded="pickerOpen" @click="openPicker">
        <Icon name="plus" :size="16" />Thêm kênh
      </button>
      <div v-if="pickerOpen" class="popover" role="menu" :style="popStyle">
        <template v-for="g in pickerGroups" :key="g.name">
          <div class="pop-group">{{ g.name }}</div>
          <button v-for="it in g.items" :key="it.c.id" type="button" class="pop-item" role="menuitem" :disabled="it.disabled" @click="pick(it.c.id)">
            <Icon name="chart" :size="16" />{{ it.c.label }}<small>{{ it.reason }}</small>
          </button>
        </template>
      </div>
    </div>

    <section class="chart-card" aria-label="Biểu đồ">
      <div class="row wrap" style="justify-content: space-between; gap: 12px 16px">
        <div class="row wrap" style="gap: 4px 16px; align-items: baseline">
          <div class="tn strong" style="font-size: 15px">{{ spanText }}</div>
          <div class="fs-13 muted">{{ data ? bucketText(data.bucket_ms) : '' }}</div>
        </div>
        <span v-if="hmi" class="fs-13 muted tn">{{ updatedAt ? `Cập nhật ${fmtTime(updatedAt)}` : '' }}</span>
        <button v-else type="button" class="btn" aria-haspopup="dialog" :disabled="!st.ids.length" @click="openExport"><Icon name="download" />Xuất CSV</button>
      </div>
      <div v-if="data && legend.length" class="legend">
        <span v-for="(l, i) in legend" :key="i">
          <span v-if="l.kind === 'ln'" class="ln" :style="{ background: l.color }" />
          <span v-else-if="l.kind === 'band'" class="band" :style="{ background: l.color }" />
          <span v-else-if="l.kind === 'th'" class="th" :style="{ borderColor: l.color }" />
          <span v-else class="gap" />{{ l.text }}
        </span>
      </div>
      <div v-if="!st.ids.length" class="chart-empty">Chọn ít nhất một kênh để xem biểu đồ.</div>
      <div v-else-if="error" class="chart-empty">{{ error }}</div>
      <div v-else-if="!data" class="chart-empty"><div class="spinner" role="status" aria-label="Đang tải" /></div>
      <div v-else-if="!hasPoints" class="chart-empty">Không có dữ liệu trong khoảng thời gian này.</div>
      <HistoryChart v-else :data="data" :colors="st.colors" :height="hmi ? 440 : 480" />
      <div v-if="data && (stats.length || gapNote)" class="chart-stats">
        <div v-for="s in stats" :key="s.id" class="tn">
          <span class="strong" :style="{ color: s.color }">{{ s.label }}</span>{{ s.text }}
        </div>
        <div v-if="gapNote" class="muted ml-auto">{{ gapNote }}</div>
      </div>
      <div v-if="loading && data" class="small muted">Đang tải…</div>
    </section>

    <Modal v-if="exp.open" title="Xuất CSV" size="sm" @close="exp.open = false">
      <div class="kv tight fs-13">
        <span>Kênh</span><span>{{ st.ids.map((id) => `${chan(id)?.label ?? id} · ${chan(id)?.zone ?? ''}`).join(', ') }}</span>
        <span>Khoảng</span><span class="tn">{{ fmtDMHM(exp.from) }} – {{ fmtDMHM(exp.to) }}</span>
      </div>
      <fieldset class="col gap-6">
        <legend class="strong">Độ phân giải</legend>
        <label
          v-for="r in EXPORT_RES"
          :key="r.id"
          class="choice"
          :class="{ on: exp.res === r.id }"
          style="align-items: center; height: 44px; padding-top: 0; padding-bottom: 0"
        >
          <input v-model="exp.res" type="radio" name="res" :value="r.id" />
          <span class="grow" style="font-size: 14px">{{ r.label }}</span>
          <span class="tn fs-13 muted">{{ exp.counts[r.id] != null ? `${fmtNum(exp.counts[r.id], 0)} dòng` : '…' }}</span>
        </label>
      </fieldset>
      <div class="small text-3" style="padding: 10px 12px; border-radius: 8px; background: var(--surface-2); line-height: 18px">{{ expNote }}</div>
      <template #foot>
        <button type="button" class="btn" @click="exp.open = false">Hủy</button>
        <button type="button" class="btn primary" @click="doExport"><Icon name="download" />Tải xuống</button>
      </template>
    </Modal>
  </div>
</template>

<script setup lang="ts">
// Quản trị · Chẩn đoán (spec mục 8.6): trạng thái từng thiết bị, tỷ lệ lỗi 1 giờ và 24 giờ, bộ đếm theo loại lỗi kèm
// nguyên nhân hay gặp, log frame thô theo từng kết nối (tự tắt sau 10 phút), trạng thái hệ thống.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import Icon from '../../components/Icon.vue';
import { api, download } from '../../lib/api';
import { ERROR_KIND, WORKER_STATE } from '../../lib/admin';
import { fmtBytes, fmtDMHM, fmtDateTime, fmtDuration, fmtNum, fmtTime, fmtWhen, shortName } from '../../lib/format';
import type { CollectorInfo, Device, WorkerInfo } from '../../lib/types';
import { attempt, toast } from '../../lib/ui';

interface DiagDevice extends Device {
  errors_1h: number;
  requests_1h: number;
  errors_24h: number;
  requests_24h: number;
  avg_rtt_ms: number | null;
  last_error_kind: string | null;
  last_error_ts: number | null;
}

interface Diag {
  now: number;
  collector: CollectorInfo;
  system: {
    free_bytes: number | null;
    db_bytes: number;
    last_backup: { ts: number; file: string; size: number } | null;
    cpu_temp: number | null;
    clock_synced: boolean | null;
    rtc: boolean;
  };
  devices: DiagDevice[];
  errors_24h: Record<string, number>;
  events: { id: number; ts: number; device_id: number; device_name: string | null; type: string; detail: string | null }[];
  connections: { id: number; name: string; type: string; worker: WorkerInfo | null }[];
}

interface Frame {
  id: number;
  ts: number;
  dir: 'TX' | 'RX';
  hex: string;
  note: string | null;
}

const CAUSES: Record<string, string> = {
  timeout: 'Sai unit ID, sai baud rate, đấu ngược A/B, đứt dây, cảm biến mất nguồn',
  crc: 'Nhiễu, thiếu điện trở đầu cuối, sai parity, 2 thiết bị trùng địa chỉ',
  exception: 'Sai địa chỉ thanh ghi hoặc function code',
  sensor: 'Node vẫn trả lời nhưng báo cảm biến bên trong hỏng',
  io: 'Adapter USB bị rút, cổng serial bị chương trình khác chiếm, gateway mất mạng',
};

const EVENT_NAMES: Record<string, string> = {
  online: 'trực tuyến trở lại',
  offline: 'mất kết nối',
  sensor_fault: 'báo lỗi cảm biến',
  sensor_ok: 'cảm biến bình thường lại',
};

const diag = ref<Diag | null>(null);
const frameConn = ref<number | null>(null);
const frames = ref<Frame[]>([]);
const frameUntil = ref<number | null>(null);
const toggling = ref(false);
let timer: ReturnType<typeof setInterval> | undefined;
let frameTimer: ReturnType<typeof setInterval> | undefined;

async function load(): Promise<void> {
  diag.value = await api.get<Diag>('/api/admin/diagnostics');
  if (frameConn.value == null) frameConn.value = diag.value.connections[0]?.id ?? null;
}

async function loadFrames(): Promise<void> {
  if (frameConn.value == null) return;
  const r = await api.get<{ until: number | null; rows: Frame[] }>(`/api/admin/connections/${frameConn.value}/frame-log?limit=120`);
  frames.value = r.rows;
  frameUntil.value = r.until;
}

async function toggleFrames(): Promise<void> {
  if (frameConn.value == null) return;
  toggling.value = true;
  const on = !frameUntil.value;
  const r = await attempt(() => api.post<{ until: number | null }>(`/api/admin/connections/${frameConn.value}/frame-log`, { enabled: on }));
  toggling.value = false;
  if (r) {
    frameUntil.value = r.until;
    toast(on ? 'Đã bật log frame; tự tắt sau 10 phút' : 'Đã tắt log frame');
    await attempt(loadFrames);
  }
}

watch(frameConn, () => {
  frames.value = [];
  void attempt(loadFrames);
});

const rate = (err: number, total: number): string => (total ? `${fmtNum((err / total) * 100, err && err / total < 0.01 ? 2 : 1)}%` : '—');
const totalErrors = computed(() => Object.values(diag.value?.errors_24h ?? {}).reduce((a, b) => a + b, 0));
const now = computed(() => diag.value?.now ?? Date.now());

function stateText(d: DiagDevice): { dot: string; text: string } {
  if (d.state === 'online') return { dot: '', text: 'Trực tuyến' };
  if (d.state === 'offline') return { dot: 'err', text: d.since ? `Mất kết nối từ ${fmtWhen(d.since, now.value)}` : 'Mất kết nối' };
  if (d.state === 'disabled') return { dot: 'off', text: 'Đang tắt' };
  if (d.state === 'stale') return { dot: 'info', text: 'Dữ liệu cũ' };
  return { dot: 'off', text: 'Chưa có dữ liệu' };
}

onMounted(() => {
  void attempt(load);
  timer = setInterval(() => void load().catch(() => undefined), 10_000);
  frameTimer = setInterval(() => {
    if (frameUntil.value) void loadFrames().catch(() => undefined);
  }, 2000);
});
onBeforeUnmount(() => {
  clearInterval(timer);
  clearInterval(frameTimer);
});
</script>

<template>
  <div class="col gap-20">
    <div class="page-head">
      <div class="title-block">
        <h1>Chẩn đoán</h1>
        <div class="page-sub">Trạng thái thiết bị, lỗi đọc theo loại và log frame thô để dò lỗi khi lắp đặt</div>
      </div>
      <button type="button" class="btn" @click="attempt(load)"><Icon name="refresh" />Làm mới</button>
    </div>

    <div v-if="!diag" class="loading"><div class="spinner" role="status" aria-label="Đang tải" /></div>
    <template v-else>
      <div class="stats">
        <div class="stat">
          <span class="k">Collector</span>
          <span class="v"><span class="dot lg" :class="diag.collector.online ? '' : 'err'" />{{ diag.collector.online ? 'Đang chạy' : 'Đang dừng' }}</span>
          <span class="d tn">{{
            diag.collector.online && diag.collector.started_at
              ? `Chạy được ${fmtDuration((diag.now - diag.collector.started_at) / 1000)} · ghi ${fmtTime(diag.collector.last_commit_at)}`
              : 'Không ghi dữ liệu mới'
          }}</span>
        </div>
        <div class="stat">
          <span class="k">Ổ đĩa còn trống</span>
          <span class="v tn">{{ fmtBytes(diag.system.free_bytes) }}</span>
          <span class="d tn">Cơ sở dữ liệu {{ fmtBytes(diag.system.db_bytes) }}</span>
        </div>
        <div class="stat">
          <span class="k">Nhiệt độ CPU</span>
          <span class="v tn">{{ diag.system.cpu_temp != null ? `${fmtNum(diag.system.cpu_temp, 1)} °C` : '—' }}</span>
          <span class="d">{{ diag.system.cpu_temp != null && diag.system.cpu_temp >= 80 ? 'Nóng: Datalogger có thể tự giảm xung' : 'Đọc từ thermal_zone0' }}</span>
        </div>
        <div class="stat">
          <span class="k">Đồng hồ</span>
          <span class="v">
            <span class="dot lg" :class="diag.system.clock_synced === false ? 'warn' : diag.system.clock_synced ? '' : 'off'" />
            {{ diag.system.clock_synced === false ? 'Chưa đồng bộ' : diag.system.clock_synced ? 'Đã đồng bộ' : 'Chưa rõ' }}
          </span>
          <span class="d">{{ diag.system.rtc ? 'Có RTC giữ giờ khi mất điện' : 'Không có RTC: cần NTP sau mỗi lần khởi động' }}</span>
        </div>
      </div>

      <div v-if="diag.collector.clock_warning" class="banner warn sm"><Icon name="clock" /><div>{{ diag.collector.clock_warning }}</div></div>

      <section class="col gap-12">
        <h2 class="panel-title">Thiết bị</h2>
        <div v-if="!diag.devices.length" class="empty"><h2>Chưa có thiết bị nào</h2></div>
        <div v-else class="tbl-wrap">
          <table class="tbl">
            <thead>
              <tr>
                <th>Thiết bị</th>
                <th>Trạng thái</th>
                <th>Lần đọc tốt gần nhất</th>
                <th class="num">Lỗi 1 giờ</th>
                <th class="num">Lỗi 24 giờ</th>
                <th class="num">Phản hồi TB</th>
                <th>Lỗi gần nhất</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="d in diag.devices" :key="d.id">
                <td>
                  <div class="col">
                    <span class="strong">{{ shortName(d.name) }}</span><span class="small muted">{{ d.zone }} · {{ d.connection_name }} · ID {{ d.unit_id }}</span>
                  </div>
                </td>
                <td><span class="row gap-8 nowrap"><span class="dot" :class="stateText(d).dot" />{{ stateText(d).text }}</span></td>
                <td class="tn nowrap">{{ d.last_ok_at ? fmtWhen(d.last_ok_at, diag.now) : '—' }}</td>
                <td class="num tn">{{ rate(d.errors_1h, d.requests_1h) }}<div class="small muted">{{ d.errors_1h }}/{{ d.requests_1h }}</div></td>
                <td class="num tn">{{ rate(d.errors_24h, d.requests_24h) }}<div class="small muted">{{ d.errors_24h }}/{{ d.requests_24h }}</div></td>
                <td class="num tn">{{ d.avg_rtt_ms != null ? `${fmtNum(d.avg_rtt_ms, 0)} ms` : '—' }}</td>
                <td class="small" style="max-width: 320px">
                  <template v-if="d.last_error">
                    <span class="strong">{{ ERROR_KIND[d.last_error_kind ?? ''] ?? d.last_error_kind }}</span>
                    {{ d.last_error_ts ? `· ${fmtDMHM(d.last_error_ts)}` : '' }}<br />{{ d.last_error }}
                  </template>
                  <span v-else class="muted">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div class="split even">
        <section class="panel p20">
          <div class="panel-head">
            <h2 class="panel-title sm">Lỗi theo loại, 24 giờ</h2>
            <span class="small muted tn">{{ totalErrors }} lỗi</span>
          </div>
          <table class="tbl compact plain">
            <thead>
              <tr><th>Loại lỗi</th><th class="num">Số lần</th><th>Nguyên nhân thường gặp</th></tr>
            </thead>
            <tbody>
              <tr v-for="(n, k) in diag.errors_24h" :key="k">
                <td class="strong nowrap">{{ ERROR_KIND[k] ?? k }}</td>
                <td class="num tn">{{ fmtNum(n, 0) }}</td>
                <td class="small text-3">{{ CAUSES[k] ?? '' }}</td>
              </tr>
            </tbody>
          </table>
        </section>
        <section class="panel p20">
          <h2 class="panel-title sm">Sự kiện gần đây</h2>
          <div v-if="!diag.events.length" class="small muted">Chưa có sự kiện nào.</div>
          <div v-else class="col gap-8" style="max-height: 320px; overflow: auto">
            <div v-for="e in diag.events" :key="e.id" class="row gap-10 fs-13" style="align-items: flex-start">
              <span class="tn muted nowrap" style="width: 88px">{{ fmtDMHM(e.ts) }}</span>
              <span class="grow"
                ><span class="strong">{{ shortName(e.device_name) }}</span> {{ EVENT_NAMES[e.type] ?? e.type }}{{ e.detail ? `: ${e.detail}` : '' }}</span
              >
            </div>
          </div>
        </section>
      </div>

      <section class="panel p20">
        <div class="panel-head">
          <h2 class="panel-title sm">Log frame thô</h2>
          <select v-model="frameConn" class="input sm" style="width: auto" aria-label="Kết nối">
            <option v-for="c in diag.connections" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </div>
        <div class="row wrap gap-8">
          <span v-for="c in diag.connections.filter((x) => x.id === frameConn)" :key="c.id" class="small text-3">
            Worker: {{ c.worker ? (WORKER_STATE[c.worker.state]?.text ?? c.worker.state) : 'collector dừng' }}{{
              c.worker?.cycle_ms ? ` · vòng đọc ${fmtNum(c.worker.cycle_ms / 1000, 2)} s` : ''
            }}{{ c.worker?.overload ? ` · ${c.worker.overload}` : '' }}
          </span>
          <span class="grow" />
          <span v-if="frameUntil" class="badge ok tn">Đang ghi đến {{ fmtTime(frameUntil) }}</span>
          <button type="button" class="btn sm" :class="{ busy: toggling }" :disabled="frameConn == null" @click="toggleFrames">
            <Icon :name="frameUntil ? 'stop' : 'play'" />{{ frameUntil ? 'Tắt log' : 'Bật log 10 phút' }}
          </button>
          <button type="button" class="btn sm" :disabled="frameConn == null" @click="download(`/api/admin/connections/${frameConn}/frame-log/download`)">
            <Icon name="download" />Tải xuống
          </button>
        </div>
        <div v-if="frames.length" class="frames" aria-live="off">
          <div v-for="f in frames" :key="f.id" class="fr" :class="{ rx: f.dir === 'RX' && !f.note, err: !!f.note }">
            <span class="muted">{{ fmtTime(f.ts) }}.{{ String(f.ts % 1000).padStart(3, '0') }}</span>
            <span>{{ f.dir }}</span>
            <span class="hex">{{ f.hex || '(không nhận được byte nào)' }}{{ f.note ? ` · ${f.note}` : '' }}</span>
            <span />
          </div>
        </div>
        <div v-else class="small muted">
          {{ frameUntil ? 'Đang chờ frame đầu tiên…' : 'Log đang tắt. Bật để xem từng frame gửi và nhận (hex, có thời điểm); tự tắt sau 10 phút để không làm đầy ổ.' }}
        </div>
      </section>

      <div class="small muted">
        Backup gần nhất: {{ diag.system.last_backup ? `${fmtDateTime(diag.system.last_backup.ts)} · ${diag.system.last_backup.file} · ${fmtBytes(diag.system.last_backup.size)}` : 'chưa có' }}
      </div>
    </template>
  </div>
</template>

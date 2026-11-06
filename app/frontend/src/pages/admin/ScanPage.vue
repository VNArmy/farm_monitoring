<script setup lang="ts">
// Quản trị · Quét bus (spec mục 8.5): quét dải unit ID chạy nền trong collector, có tiến độ và nút dừng; polling trên bus
// đó tạm dừng trong lúc quét. Đổi địa chỉ hoặc baud rate cảm biến qua FC 06 khi mẫu có khai báo thanh ghi, rồi đọc lại xác nhận.
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';
import FormField from '../../components/FormField.vue';
import Icon from '../../components/Icon.vue';
import Modal from '../../components/Modal.vue';
import { api } from '../../lib/api';
import { BAUDS, connSummary, reqNum } from '../../lib/admin';
import { fmtDuration, fmtNum } from '../../lib/format';
import type { Connection, Template } from '../../lib/types';
import { attempt, toast, useFormErrors } from '../../lib/ui';

interface Hit {
  unit_id: number;
  baud: number | null;
  parity: string | null;
  stopbits: number | null;
  response: 'ok' | 'exception' | 'crc';
  code?: number;
  rtt_ms: number | null;
}

interface Job {
  id: number;
  status: 'running' | 'done' | 'error' | 'cancelled';
  connection_id: number;
  progress: {
    bauds?: (number | null)[];
    baud?: number | null;
    current_id?: number;
    done?: number;
    total?: number;
    found?: Hit[];
    eta_s?: number | null;
  };
  result: { found: Hit[]; error?: string; cancelled?: boolean; done?: number; total?: number } | null;
}

const conns = ref<Connection[]>([]);
const templates = ref<Template[]>([]);
const loaded = ref(false);
const form = reactive({ connection_id: null as number | null, from_id: '1', to_id: '247', timeout_ms: '200', bauds: [] as number[] });
const job = ref<Job | null>(null);
const busy = reactive({ start: false, cancel: false, set: false });
const { errors, clear, fail } = useFormErrors();
let timer: ReturnType<typeof setTimeout> | undefined;

const conn = computed(() => conns.value.find((c) => c.id === form.connection_id) ?? null);
const running = computed(() => job.value?.status === 'running');
const found = computed<Hit[]>(() => job.value?.result?.found ?? job.value?.progress.found ?? []);
const progress = computed(() => {
  const p = job.value?.progress;
  if (!p?.total) return 0;
  return Math.round(((p.done ?? 0) / p.total) * 100);
});

watch(conn, (c) => {
  if (!c) return;
  form.bauds = c.type === 'rtu' && c.params.baudrate ? [c.params.baudrate] : [];
  form.from_id = c.type === 'tcp' ? '0' : '1';
  form.to_id = c.type === 'tcp' ? '255' : '247';
});

const estimate = computed(() => {
  const a = Number(form.from_id);
  const b = Number(form.to_id);
  const t = Number(form.timeout_ms);
  if (!(b >= a) || !(t > 0)) return '';
  const n = (b - a + 1) * Math.max(1, form.bauds.length || 1);
  return `Tối đa khoảng ${fmtDuration((n * (t + 20)) / 1000)} nếu không thiết bị nào trả lời`;
});

function deviceAt(uid: number): string | null {
  return conn.value?.devices?.find((d) => d.unit_id === uid)?.name ?? null;
}

function responseText(h: Hit): string {
  if (h.response === 'ok') return 'Trả lời';
  if (h.response === 'exception') return `Exception ${h.code} (có thiết bị)`;
  return 'Khung lỗi CRC (có thể 2 thiết bị trùng ID)';
}

let pollFails = 0;
async function poll(): Promise<void> {
  const j = job.value;
  if (!j) return;
  try {
    job.value = await api.get<Job>(`/api/admin/jobs/${j.id}`);
    pollFails = 0;
  } catch (e) {
    // Lỗi thoáng qua (mạng Wi-Fi chập chờn): thử lại vài lần rồi mới báo.
    if (++pollFails < 5) {
      timer = setTimeout(poll, 1000);
      return;
    }
    toast(e instanceof Error ? e.message : String(e), 'err');
    return;
  }
  if (job.value.status === 'running') timer = setTimeout(poll, 500);
  else {
    const n = job.value.result?.found.length ?? 0;
    if (job.value.status === 'error') toast(job.value.result?.error ?? 'Quét bị lỗi', 'err');
    else toast(job.value.status === 'cancelled' ? `Đã dừng quét; tìm thấy ${n} thiết bị` : `Quét xong; tìm thấy ${n} thiết bị`);
    await attempt(loadConns);
  }
}

async function start(): Promise<void> {
  const c = conn.value;
  if (!c) return;
  clear();
  busy.start = true;
  try {
    const r = await api.post<{ job_id: number }>(`/api/admin/connections/${c.id}/scan`, {
      from_id: reqNum(form.from_id, 'from_id', true),
      to_id: reqNum(form.to_id, 'to_id', true),
      timeout_ms: reqNum(form.timeout_ms, 'timeout_ms', true),
      bauds: c.type === 'rtu' ? form.bauds : [],
    });
    job.value = { id: r.job_id, status: 'running', connection_id: c.id, progress: {}, result: null };
    clearTimeout(timer);
    timer = setTimeout(poll, 300);
  } catch (e) {
    fail(e);
  } finally {
    busy.start = false;
  }
}

async function cancel(): Promise<void> {
  const j = job.value;
  if (!j) return;
  busy.cancel = true;
  await attempt(() => api.post(`/api/admin/jobs/${j.id}/cancel`));
  busy.cancel = false;
}

// --- Đổi địa chỉ -------------------------------------------------------------------------------
const addrTemplates = computed(() => templates.value.filter((t) => t.address_register != null));
const sa = reactive({
  open: false,
  template_id: null as number | null,
  current_id: '',
  current_baud: null as number | null,
  new_id: '',
  new_baud: null as number | null,
  sure: false,
  result: null as { ok: boolean; message: string; steps: { label: string; ok: boolean; message?: string }[] } | null,
});
const saTemplate = computed(() => templates.value.find((t) => t.id === sa.template_id) ?? null);
const saBauds = computed(() => (saTemplate.value?.baud_register != null && saTemplate.value.baud_codes ? Object.keys(saTemplate.value.baud_codes).map(Number) : []));

function openSetAddress(h?: Hit): void {
  const c = conn.value;
  sa.template_id = addrTemplates.value[0]?.id ?? null;
  sa.current_id = h ? String(h.unit_id) : '1';
  sa.current_baud = h?.baud ?? (c?.type === 'rtu' ? (c.params.baudrate ?? null) : null);
  sa.new_id = '';
  sa.new_baud = sa.current_baud;
  sa.sure = false;
  sa.result = null;
  clear();
  sa.open = true;
}

async function setAddress(): Promise<void> {
  const c = conn.value;
  if (!c) return;
  clear();
  busy.set = true;
  try {
    const body = {
      template_id: sa.template_id,
      current_id: reqNum(sa.current_id, 'current_id', true),
      current_baud: c.type === 'rtu' ? sa.current_baud : null,
      new_id: reqNum(sa.new_id, 'new_id', true),
      new_baud: c.type === 'rtu' && saBauds.value.length ? sa.new_baud : null,
    };
    sa.result = await api.post(`/api/admin/connections/${c.id}/set-address`, body);
    if (sa.result?.ok) toast(sa.result.message);
  } catch (e) {
    fail(e);
  } finally {
    busy.set = false;
  }
}

async function loadConns(): Promise<void> {
  conns.value = await api.get<Connection[]>('/api/admin/connections');
}

onMounted(async () => {
  await attempt(async () => {
    const [, ts] = await Promise.all([loadConns(), api.get<Template[]>('/api/admin/templates')]);
    templates.value = ts;
  });
  loaded.value = true;
  form.connection_id = conns.value.find((c) => c.type === 'rtu')?.id ?? conns.value[0]?.id ?? null;
});
onBeforeUnmount(() => clearTimeout(timer));
</script>

<template>
  <div class="col gap-20">
    <div class="page-head">
      <div class="title-block">
        <h1>Quét bus</h1>
        <div class="page-sub">Tìm địa chỉ các cảm biến trên bus, đổi địa chỉ hoặc baud rate khi lắp đặt</div>
      </div>
      <button type="button" class="btn" :disabled="!conn || !addrTemplates.length" @click="openSetAddress()"><Icon name="edit" />Đổi địa chỉ cảm biến</button>
    </div>

    <div v-if="!loaded" class="loading"><div class="spinner" role="status" aria-label="Đang tải" /></div>
    <div v-else-if="!conns.length" class="empty">
      <h2>Chưa có kết nối nào</h2>
      <p>Thêm một bus RS-485 hoặc Modbus TCP trước khi quét.</p>
      <RouterLink class="btn primary" to="/quan-tri/ket-noi">Thêm kết nối</RouterLink>
    </div>
    <div v-else class="split w400">
      <form class="panel p20" novalidate @submit.prevent="start">
        <h2 class="panel-title sm">Quét địa chỉ</h2>
        <FormField label="Kết nối" input-id="q-kn" :hint="conn ? connSummary(conn) : ''">
          <select id="q-kn" v-model="form.connection_id" class="input" :disabled="running">
            <option v-for="c in conns" :key="c.id" :value="c.id">{{ c.name }} ({{ c.type === 'rtu' ? 'RTU' : 'TCP' }})</option>
          </select>
        </FormField>
        <div class="form-grid tight" style="grid-template-columns: repeat(3, minmax(0, 1fr))">
          <FormField label="Từ ID" input-id="q-tu" :error="errors.from_id" sm>
            <input id="q-tu" v-model="form.from_id" data-field="from_id" class="input sm tn" :class="{ invalid: errors.from_id }" inputmode="numeric" :disabled="running" />
          </FormField>
          <FormField label="Đến ID" input-id="q-den" :error="errors.to_id" sm>
            <input id="q-den" v-model="form.to_id" data-field="to_id" class="input sm tn" :class="{ invalid: errors.to_id }" inputmode="numeric" :disabled="running" />
          </FormField>
          <FormField label="Timeout" input-id="q-to" :error="errors.timeout_ms" sm>
            <div class="affix" style="height: 36px"><input id="q-to" v-model="form.timeout_ms" data-field="timeout_ms" class="tn" inputmode="numeric" :disabled="running" /><span>ms</span></div>
          </FormField>
        </div>
        <fieldset v-if="conn?.type === 'rtu'" data-field="bauds">
          <legend>Baud rate cần thử</legend>
          <div class="row wrap gap-12">
            <label v-for="b in BAUDS" :key="b" class="check sm tn"><input v-model="form.bauds" type="checkbox" :value="b" :disabled="running" />{{ b }}</label>
          </div>
          <span v-if="errors.bauds" class="hint err">{{ errors.bauds }}</span>
        </fieldset>
        <div class="banner note sm">
          <Icon name="info" />
          <div>Polling trên bus này tạm dừng trong lúc quét. {{ estimate }}.</div>
        </div>
        <div class="row" style="justify-content: flex-end; gap: 8px">
          <button v-if="running" type="button" class="btn" :class="{ busy: busy.cancel }" @click="cancel"><Icon name="stop" />Dừng</button>
          <button v-else type="submit" class="btn primary" :class="{ busy: busy.start }" :disabled="busy.start || !conn"><Icon name="scan" />Bắt đầu quét</button>
        </div>
      </form>

      <section class="panel p20">
        <div class="panel-head">
          <h2 class="panel-title sm">Kết quả</h2>
          <span v-if="job" class="small muted tn">{{ found.length }} thiết bị</span>
        </div>
        <div v-if="!job" class="small muted">Chưa quét. Chọn kết nối và dải ID rồi bấm Bắt đầu quét.</div>
        <template v-else>
          <div class="col gap-6">
            <div class="progress" role="progressbar" :aria-valuenow="progress" aria-valuemin="0" aria-valuemax="100"><div :style="{ width: `${progress}%` }" /></div>
            <div class="row small muted tn" style="justify-content: space-between">
              <span v-if="running">
                Đang thử ID {{ job.progress.current_id ?? '…' }}{{ job.progress.baud ? ` ở ${job.progress.baud} baud` : '' }} ·
                {{ job.progress.done ?? 0 }}/{{ job.progress.total ?? '…' }}
              </span>
              <span v-else>{{ job.status === 'done' ? 'Đã quét xong' : job.status === 'cancelled' ? 'Đã dừng' : `Lỗi: ${job.result?.error ?? ''}` }}</span>
              <span v-if="running && job.progress.eta_s != null">còn khoảng {{ fmtDuration(job.progress.eta_s) }}</span>
            </div>
          </div>
          <div v-if="found.length" class="tbl-wrap" style="padding: 0 8px">
            <table class="tbl compact">
              <thead>
                <tr><th>ID</th><th v-if="conn?.type === 'rtu'">Baud</th><th>Phản hồi</th><th class="num">Thời gian</th><th>Thiết bị đã khai báo</th><th /></tr>
              </thead>
              <tbody>
                <tr v-for="h in found" :key="`${h.unit_id}-${h.baud}`">
                  <td class="tn strong">{{ h.unit_id }}</td>
                  <td v-if="conn?.type === 'rtu'" class="tn">{{ h.baud }} 8{{ h.parity }}{{ h.stopbits }}</td>
                  <td :class="{ 'hint err': h.response === 'crc' }">{{ responseText(h) }}</td>
                  <td class="num tn">{{ h.rtt_ms != null ? `${fmtNum(h.rtt_ms, 0)} ms` : '—' }}</td>
                  <td>{{ deviceAt(h.unit_id) ?? '—' }}</td>
                  <td class="num nowrap">
                    <RouterLink
                      v-if="!deviceAt(h.unit_id) && (h.baud == null || h.baud === conn?.params.baudrate)"
                      class="btn sm ghost"
                      :to="{ path: '/quan-tri/thiet-bi', query: { moi: '1', 'ket-noi': String(job.connection_id), id: String(h.unit_id) } }"
                      >Thêm thiết bị</RouterLink
                    >
                    <button v-if="addrTemplates.length && !running" type="button" class="btn sm ghost" @click="openSetAddress(h)">Đổi địa chỉ</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else-if="!running" class="small muted">Không thiết bị nào trả lời. Kiểm tra baud rate, parity, đấu dây A/B và nguồn cảm biến.</div>
        </template>
      </section>
    </div>

    <Modal v-if="sa.open" title="Đổi địa chỉ cảm biến" size="sm" @close="sa.open = false">
      <div class="banner warn sm">
        <Icon name="warn" />
        <div>
          Chỉ để <span class="strong">một</span> cảm biến mang địa chỉ hiện tại trên bus khi ghi, tránh 2 con cùng nhận lệnh. Một số model cần tắt bật
          nguồn mới nhận baud rate mới.
        </div>
      </div>
      <FormField label="Mẫu thiết bị" input-id="sa-mau" :error="errors.template_id" hint="Chỉ mẫu có khai báo thanh ghi địa chỉ">
        <select id="sa-mau" v-model="sa.template_id" data-field="template_id" class="input">
          <option v-for="t in addrTemplates" :key="t.id" :value="t.id">{{ t.name }} (thanh ghi {{ t.address_register }})</option>
        </select>
      </FormField>
      <div class="form-grid tight">
        <FormField label="ID hiện tại" input-id="sa-cur" :error="errors.current_id" sm>
          <input id="sa-cur" v-model="sa.current_id" data-field="current_id" class="input sm tn" inputmode="numeric" />
        </FormField>
        <FormField label="ID mới" input-id="sa-new" :error="errors.new_id" sm>
          <input id="sa-new" v-model="sa.new_id" data-field="new_id" class="input sm tn" :class="{ invalid: errors.new_id }" inputmode="numeric" />
        </FormField>
        <template v-if="conn?.type === 'rtu'">
          <FormField label="Baud hiện tại" input-id="sa-cb" sm>
            <select id="sa-cb" v-model.number="sa.current_baud" class="input sm">
              <option v-for="b in BAUDS" :key="b" :value="b">{{ b }}</option>
            </select>
          </FormField>
          <FormField label="Baud mới" input-id="sa-nb" :hint="saBauds.length ? '' : 'Mẫu này không đổi được baud rate'" sm>
            <select id="sa-nb" v-model.number="sa.new_baud" class="input sm" :disabled="!saBauds.length">
              <option v-for="b in saBauds.length ? saBauds : [sa.current_baud]" :key="b ?? 0" :value="b">{{ b }}</option>
            </select>
          </FormField>
        </template>
      </div>
      <label class="check sm"><input v-model="sa.sure" type="checkbox" />Trên bus chỉ có một cảm biến ở ID {{ sa.current_id || '…' }}</label>
      <div v-if="sa.result" class="banner sm" :class="sa.result.ok ? 'ok' : 'danger'" role="status">
        <Icon :name="sa.result.ok ? 'check' : 'xCircle'" />
        <div class="col gap-4">
          <span class="strong">{{ sa.result.message }}</span>
          <span v-for="(s, i) in sa.result.steps" :key="i">{{ s.ok ? '✓' : '✗' }} {{ s.label }}{{ s.message ? `: ${s.message}` : '' }}</span>
        </div>
      </div>
      <template #foot>
        <button type="button" class="btn" @click="sa.open = false">Đóng</button>
        <button type="button" class="btn primary" :class="{ busy: busy.set }" :disabled="!sa.sure || busy.set || !sa.template_id" @click="setAddress">
          Ghi địa chỉ mới
        </button>
      </template>
    </Modal>
  </div>
</template>

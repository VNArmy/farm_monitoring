<script setup lang="ts">
// Quản trị · Kết nối (spec mục 8.2): mỗi kết nối là một bus RS-485 (một cổng serial) hoặc một địa chỉ Modbus TCP.
// Kiểm tra chạy qua collector với tham số đang nhập, chưa cần lưu.
import { computed, onMounted, reactive, ref } from 'vue';
import FormField from '../../components/FormField.vue';
import Icon from '../../components/Icon.vue';
import { api } from '../../lib/api';
import { BAUDS, PARITY_NAMES, WORKER_STATE, connSummary, connTarget, reqNum, str } from '../../lib/admin';
import { fmtNum, fmtTime } from '../../lib/format';
import type { Connection, SerialPort, WorkerInfo } from '../../lib/types';
import { attempt, confirmDialog, toast, useFormErrors } from '../../lib/ui';

interface Draft {
  id: number | null;
  name: string;
  type: 'rtu' | 'tcp';
  enabled: boolean;
  port: string;
  baudrate: number;
  parity: 'N' | 'E' | 'O';
  stopbits: 1 | 2;
  host: string;
  tcpPort: string;
  framing: 'tcp' | 'rtu_over_tcp';
  timeout_ms: string;
  retries: number;
  gap_ms: string;
}

const conns = ref<Connection[]>([]);
const ports = ref<SerialPort[]>([]);
const loaded = ref(false);
const draft = ref<Draft | null>(null);
const check = ref<{ ok: boolean; message: string; at: number } | null>(null);
const busy = reactive({ save: false, test: false, del: false, ports: false });
const { errors, clear, fail } = useFormErrors();

function blank(type: 'rtu' | 'tcp'): Draft {
  return {
    id: null,
    name: type === 'tcp' ? 'Gateway RS-485/Ethernet' : 'Bus RS-485',
    type,
    enabled: true,
    port: ports.value.find((p) => !conns.value.some((c) => c.type === 'rtu' && c.params.port === p.path))?.path ?? '',
    baudrate: 9600,
    parity: 'N',
    stopbits: 1,
    host: '',
    tcpPort: '502',
    framing: 'tcp',
    timeout_ms: type === 'tcp' ? '1000' : '500',
    retries: 1,
    gap_ms: type === 'tcp' ? '0' : '20',
  };
}

function fromConn(c: Connection): Draft {
  const p = c.params;
  return {
    id: c.id,
    name: c.name,
    type: c.type,
    enabled: c.enabled,
    port: c.type === 'rtu' ? String(p.port) : '',
    baudrate: p.baudrate ?? 9600,
    parity: p.parity ?? 'N',
    stopbits: p.stopbits ?? 1,
    host: p.host ?? '',
    tcpPort: c.type === 'tcp' ? String(p.port) : '502',
    framing: p.framing ?? 'tcp',
    timeout_ms: str(p.timeout_ms),
    retries: p.retries ?? 1,
    gap_ms: str(p.gap_ms),
  };
}

function params(d: Draft): Record<string, unknown> {
  const common = {
    timeout_ms: reqNum(d.timeout_ms, 'params.timeout_ms', true),
    retries: d.retries,
    gap_ms: reqNum(d.gap_ms, 'params.gap_ms', true),
  };
  if (d.type === 'rtu') return { port: d.port, baudrate: d.baudrate, parity: d.parity, stopbits: d.stopbits, ...common };
  return { host: d.host.trim(), port: reqNum(d.tcpPort, 'params.port', true), framing: d.framing, ...common };
}

async function load(selectId?: number | null): Promise<void> {
  const [c, p] = await Promise.all([
    api.get<Connection[]>('/api/admin/connections'),
    api.get<SerialPort[]>('/api/admin/serial-ports').catch(() => [] as SerialPort[]),
  ]);
  conns.value = c;
  ports.value = p;
  loaded.value = true;
  const want = selectId === undefined ? (draft.value?.id ?? null) : selectId;
  const sel = c.find((x) => x.id === want) ?? c[0];
  if (sel) select(sel);
}

function select(c: Connection): void {
  draft.value = fromConn(c);
  check.value = null;
  clear();
}

function add(type: 'rtu' | 'tcp'): void {
  draft.value = blank(type);
  check.value = null;
  clear();
}

async function refreshPorts(): Promise<void> {
  busy.ports = true;
  const p = await attempt(() => api.get<SerialPort[]>('/api/admin/serial-ports'));
  if (p) ports.value = p;
  busy.ports = false;
}

const portInfo = computed(() => {
  const d = draft.value;
  if (!d || d.type !== 'rtu') return '';
  const p = ports.value.find((x) => x.path === d.port);
  if (!p) return d.port ? 'Cổng này hiện không thấy trên Datalogger. Kiểm tra adapter USB đã cắm chưa.' : '';
  const parts = [p.manufacturer, p.product].filter(Boolean);
  if (p.serial_number) parts.push(`số serial ${p.serial_number}`);
  if (p.device && p.device !== p.path) parts.push(`hiện là ${p.device}`);
  let s = parts.join(' · ');
  if (p.stable && p.path.startsWith('/dev/serial/by-id')) s += `${s ? '. ' : ''}Đường dẫn by-id không đổi khi cắm lại adapter.`;
  else if (!p.stable) s += `${s ? '. ' : ''}Tên ttyUSB có thể đổi sau khi cắm lại; nên dùng /dev/serial/by-id.`;
  return s;
});

const current = computed(() => conns.value.find((c) => c.id === draft.value?.id) ?? null);
const worker = computed(() => {
  const w = current.value?.worker;
  return w && 'connection_id' in w ? (w as WorkerInfo) : null;
});
const workerBadge = computed(() => {
  const c = current.value;
  if (!c) return null;
  if (!c.enabled) return WORKER_STATE.stopped;
  if (c.worker == null) return { text: 'Collector dừng', cls: 'danger' };
  return WORKER_STATE[c.worker.state] ?? null;
});

function badgeOf(c: Connection): { text: string; cls: string } | null {
  if (!c.enabled) return { text: 'Đang tắt', cls: 'off' };
  const s = c.worker?.state;
  if (s === 'error') return { text: 'Lỗi cổng', cls: 'danger' };
  if (s === 'paused') return { text: 'Tạm dừng', cls: 'info' };
  return null;
}
function devDot(d: NonNullable<Connection['devices']>[number]): string {
  if (!d.enabled) return 'off';
  if (d.state === 'offline') return 'err';
  if (d.state === 'online') return '';
  return 'off';
}

async function test(): Promise<void> {
  const d = draft.value;
  if (!d) return;
  clear();
  busy.test = true;
  try {
    const body = { type: d.type, params: params(d) };
    const url = d.id == null ? '/api/admin/connections/test' : `/api/admin/connections/${d.id}/test`;
    check.value = await api.post<{ ok: boolean; message: string; at: number }>(url, body);
  } catch (e) {
    fail(e);
  } finally {
    busy.test = false;
  }
}

async function save(): Promise<void> {
  const d = draft.value;
  if (!d) return;
  clear();
  busy.save = true;
  try {
    const body = { name: d.name.trim(), type: d.type, enabled: d.enabled, params: params(d) };
    const saved =
      d.id == null
        ? await api.post<Connection>('/api/admin/connections', body)
        : await api.patch<Connection>(`/api/admin/connections/${d.id}`, body);
    toast(d.id == null ? `Đã thêm kết nối ${saved.name}` : `Đã lưu ${saved.name}; collector áp dụng trong vài giây`);
    await load(saved.id);
  } catch (e) {
    fail(e);
  } finally {
    busy.save = false;
  }
}

async function remove(): Promise<void> {
  const d = draft.value;
  if (!d || d.id == null) return;
  const ok = await confirmDialog('Xóa kết nối', `Xóa kết nối “${d.name}”? Thao tác này được ghi vào nhật ký.`, 'Xóa', true);
  if (!ok) return;
  busy.del = true;
  const r = await attempt(() => api.del(`/api/admin/connections/${d.id}`));
  busy.del = false;
  if (r) {
    toast(`Đã xóa ${d.name}`);
    draft.value = null;
    await load(null);
  }
}

onMounted(() => void attempt(() => load()));
</script>

<template>
  <div class="col gap-20">
    <div class="page-head">
      <div class="title-block">
        <h1>Kết nối</h1>
        <div class="page-sub">Mỗi kết nối là một bus RS-485 (một cổng serial) hoặc một địa chỉ Modbus TCP</div>
      </div>
      <div class="row wrap gap-8">
        <button type="button" class="btn" @click="add('tcp')"><Icon name="wifi" />Thêm Modbus TCP</button>
        <button type="button" class="btn primary" @click="add('rtu')"><Icon name="plus" />Thêm bus RS-485</button>
      </div>
    </div>

    <div v-if="!loaded" class="loading"><div class="spinner" role="status" aria-label="Đang tải" /></div>
    <div v-else class="split w360">
      <div class="col gap-12">
        <div v-if="!conns.length" class="empty">
          <h2>Chưa có kết nối nào</h2>
          <p>Thêm một bus RS-485 (adapter USB) hoặc một địa chỉ Modbus TCP.</p>
        </div>
        <button
          v-for="c in conns"
          :key="c.id"
          type="button"
          class="list-card"
          style="gap: 10px; padding: 18px"
          :aria-current="c.id === draft?.id"
          @click="select(c)"
        >
          <div class="row gap-8">
            <span class="strong grow" style="font-size: 15px">{{ c.name }}</span>
            <span v-if="badgeOf(c)" class="badge" :class="badgeOf(c)?.cls">{{ badgeOf(c)?.text }}</span>
            <span class="tag">{{ c.type === 'rtu' ? 'RTU' : 'TCP' }}</span>
          </div>
          <div class="mono small text-3" style="word-break: break-all; line-height: 18px">{{ connTarget(c) }}</div>
          <div class="tn fs-13" style="color: var(--text-2)">
            {{ connSummary(c) }}{{ c.worker && 'cycle_ms' in c.worker && c.worker.cycle_ms ? ` · vòng đọc ${fmtNum(c.worker.cycle_ms / 1000, 2)} s` : '' }}
          </div>
          <div v-if="c.devices?.length" class="col gap-8" style="padding-top: 10px; border-top: 1px solid var(--divider)">
            <div v-for="d in c.devices" :key="d.id" class="row gap-8 fs-13">
              <span class="dot" :class="devDot(d)" /><span class="mono tn small text-3" style="width: 44px">ID {{ d.unit_id }}</span>
              <span class="grow ellipsis">{{ d.name }}</span>
              <span class="tn small muted">{{ d.state === 'online' && d.last_rtt_ms != null ? `${Math.round(d.last_rtt_ms)} ms` : '' }}</span>
            </div>
          </div>
          <div v-else class="small muted">Chưa có thiết bị</div>
        </button>
      </div>

      <form v-if="draft" class="panel" novalidate :aria-label="draft.id == null ? 'Thêm kết nối' : `Sửa kết nối ${draft.name}`" @submit.prevent="save">
        <div class="panel-head">
          <h2 class="panel-title">{{ draft.id == null ? (draft.type === 'rtu' ? 'Thêm bus RS-485' : 'Thêm Modbus TCP') : draft.name }}</h2>
          <span v-if="workerBadge" class="badge" :class="workerBadge.cls">{{ workerBadge.text }}</span>
          <span class="tag">{{ draft.type === 'rtu' ? 'RTU' : 'TCP' }}</span>
        </div>

        <div v-if="worker?.error" class="banner danger sm"><Icon name="xCircle" /><div>{{ worker.error }}</div></div>
        <div v-if="worker?.paused_reason" class="banner info sm"><Icon name="pause" /><div>Tạm dừng đọc: {{ worker.paused_reason }}</div></div>
        <div v-if="worker?.overload" class="banner warn sm"><Icon name="warn" /><div>{{ worker.overload }}</div></div>

        <div class="form-grid">
          <FormField label="Tên kết nối" input-id="kn-ten" :error="errors.name" span2>
            <input id="kn-ten" v-model="draft.name" data-field="name" class="input" :class="{ invalid: errors.name }" maxlength="60" />
          </FormField>

          <template v-if="draft.type === 'rtu'">
            <FormField label="Cổng serial" input-id="kn-cong" :error="errors['params.port']" :hint="portInfo" span2>
              <div class="row gap-8">
                <select
                  id="kn-cong"
                  v-model="draft.port"
                  data-field="params.port"
                  class="input mono grow"
                  :class="{ invalid: errors['params.port'] }"
                  style="font-size: 13px"
                >
                  <option value="" disabled>Chọn cổng…</option>
                  <option v-if="draft.port && !ports.some((p) => p.path === draft?.port)" :value="draft.port">{{ draft.port }}</option>
                  <option v-for="p in ports" :key="p.path" :value="p.path">{{ p.path.replace('/dev/serial/by-id/', '') }}</option>
                </select>
                <button type="button" class="btn" :class="{ busy: busy.ports }" @click="refreshPorts"><Icon name="refresh" />Làm mới</button>
              </div>
            </FormField>
            <FormField label="Baud rate" input-id="kn-baud" :error="errors['params.baudrate']">
              <select id="kn-baud" v-model.number="draft.baudrate" data-field="params.baudrate" class="input">
                <option v-for="b in BAUDS" :key="b" :value="b">{{ b }}</option>
              </select>
            </FormField>
            <div class="field">
              <span class="lbl">Parity</span>
              <div class="seg full" role="group" aria-label="Parity">
                <button v-for="(n, v) in PARITY_NAMES" :key="v" type="button" :aria-pressed="draft.parity === v" @click="draft.parity = v as 'N'">{{ n }}</button>
              </div>
            </div>
            <div class="field">
              <span class="lbl">Stop bits</span>
              <div class="seg full" role="group" aria-label="Stop bits">
                <button v-for="s in [1, 2] as const" :key="s" type="button" :aria-pressed="draft.stopbits === s" @click="draft.stopbits = s">{{ s }}</button>
              </div>
              <span class="hint">Data bits cố định 8</span>
            </div>
          </template>

          <template v-else>
            <FormField label="Host" input-id="kn-host" :error="errors['params.host']">
              <input
                id="kn-host"
                v-model="draft.host"
                data-field="params.host"
                class="input mono"
                :class="{ invalid: errors['params.host'] }"
                placeholder="192.168.1.50"
                autocapitalize="none"
                spellcheck="false"
              />
            </FormField>
            <FormField label="Port" input-id="kn-port" :error="errors['params.port']">
              <input
                id="kn-port"
                v-model="draft.tcpPort"
                data-field="params.port"
                class="input mono"
                :class="{ invalid: errors['params.port'] }"
                inputmode="numeric"
              />
            </FormField>
            <fieldset class="span-2 col gap-8">
              <legend>Kiểu đóng gói</legend>
              <label class="choice" :class="{ on: draft.framing === 'tcp' }">
                <input v-model="draft.framing" type="radio" value="tcp" />
                <span><b>Modbus TCP</b><small>Thiết bị TCP gốc, hoặc gateway ở chế độ Modbus gateway (tự chuyển sang RTU)</small></span>
              </label>
              <label class="choice" :class="{ on: draft.framing === 'rtu_over_tcp' }">
                <input v-model="draft.framing" type="radio" value="rtu_over_tcp" />
                <span><b>RTU over TCP</b><small>Gateway truyền trong suốt: frame RTU kèm CRC đi nguyên trong TCP</small></span>
              </label>
            </fieldset>
          </template>

          <FormField label="Timeout" input-id="kn-timeout" :error="errors['params.timeout_ms']">
            <div class="affix" :class="{ invalid: errors['params.timeout_ms'] }">
              <input id="kn-timeout" v-model="draft.timeout_ms" data-field="params.timeout_ms" class="tn" inputmode="numeric" /><span>ms</span>
            </div>
          </FormField>
          <FormField label="Số lần thử lại" input-id="kn-retry" :error="errors['params.retries']">
            <select id="kn-retry" v-model.number="draft.retries" class="input">
              <option v-for="n in [0, 1, 2, 3]" :key="n" :value="n">{{ n }}</option>
            </select>
          </FormField>
          <FormField label="Nghỉ giữa 2 request" input-id="kn-gap" :error="errors['params.gap_ms']">
            <div class="affix" :class="{ invalid: errors['params.gap_ms'] }">
              <input id="kn-gap" v-model="draft.gap_ms" data-field="params.gap_ms" class="tn" inputmode="numeric" /><span>ms</span>
            </div>
          </FormField>
          <div class="field" style="justify-content: flex-end">
            <label class="check"><input v-model="draft.enabled" type="checkbox" />Đang dùng (collector đọc kết nối này)</label>
          </div>
          <div v-if="draft.type === 'tcp'" class="hint span-2">
            Collector gửi từng request một trên mỗi kết nối TCP, vì phía sau gateway vẫn là bus half-duplex.
          </div>
        </div>

        <div v-if="check" class="banner sm" :class="check.ok ? 'ok' : 'danger'" role="status">
          <Icon :name="check.ok ? 'check' : 'xCircle'" />
          <div class="tn"><span class="strong">Kiểm tra lúc {{ fmtTime(check.at) }}:</span> {{ check.message }}</div>
        </div>

        <div class="row wrap" style="gap: 8px; padding-top: 4px">
          <button
            v-if="draft.id != null"
            type="button"
            class="btn danger"
            :disabled="busy.del || !!current?.devices?.length"
            :title="current?.devices?.length ? 'Còn thiết bị dùng kết nối này' : undefined"
            @click="remove"
          >
            Xóa kết nối
          </button>
          <span class="grow" />
          <button type="button" class="btn" :class="{ busy: busy.test }" :disabled="busy.test" @click="test"><Icon name="play" />Kiểm tra</button>
          <button type="submit" class="btn primary" :class="{ busy: busy.save }" :disabled="busy.save"><Icon name="save" />Lưu</button>
        </div>
      </form>
    </div>
  </div>
</template>

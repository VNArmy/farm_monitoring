<script setup lang="ts">
// Quản trị · Thiết bị (spec mục 4.3, 8.4): kết nối, unit ID, mẫu, khu vực, chu kỳ đọc; nhãn, thang hiển thị và ngưỡng
// từng kênh kèm thanh xem trước vẽ giống HMI. Đọc thử chạy được trước khi lưu. Xóa là xóa mềm.
import { computed, onMounted, reactive, ref } from 'vue';
import { RouterLink, useRoute } from 'vue-router';
import FormField from '../../components/FormField.vue';
import HexFrame from '../../components/HexFrame.vue';
import Icon from '../../components/Icon.vue';
import RangeBar from '../../components/RangeBar.vue';
import { api } from '../../lib/api';
import { ERROR_KIND, connSummary, num, reqNum, str } from '../../lib/admin';
import { fmtAuto, fmtDMHM, fmtNum, fmtTime, fmtWhen, parseNum } from '../../lib/format';
import type { AdminDevice, ChannelDef, Connection, Template, TestReadResult } from '../../lib/types';
import { attempt, confirmDialog, toast, useFormErrors } from '../../lib/ui';

interface ChSet {
  label: string;
  display_min: string;
  display_max: string;
  alarm_low: string;
  alarm_high: string;
  enabled: boolean;
}

interface Draft {
  id: number | null;
  name: string;
  zone: string;
  connection_id: number | null;
  unit_id: string;
  template_id: number | null;
  poll_interval_s: string;
  enabled: boolean;
  channels: Record<string, ChSet>;
}

const HL_COLORS = ['#FDEBD3', '#E3EFE9', '#E6ECF3', '#F1E4F7', '#FBE3E1', '#EFEBD3'];

const route = useRoute();
const devices = ref<AdminDevice[]>([]);
const templates = ref<Template[]>([]);
const conns = ref<Connection[]>([]);
const loaded = ref(false);
const draft = ref<Draft | null>(null);
const result = ref<TestReadResult | null>(null);
const busy = reactive({ save: false, del: false, test: false });
const { errors, clear, fail } = useFormErrors();

const tpl = computed(() => templates.value.find((t) => t.id === draft.value?.template_id) ?? null);
const current = computed(() => devices.value.find((d) => d.id === draft.value?.id) ?? null);
const conn = computed(() => conns.value.find((c) => c.id === draft.value?.connection_id) ?? null);

function chSet(c: ChannelDef, saved?: AdminDevice['channels'][number]): ChSet {
  return {
    label: saved && saved.label !== c.label ? saved.label : '',
    display_min: str(saved?.display_min),
    display_max: str(saved?.display_max),
    alarm_low: str(saved?.alarm_low),
    alarm_high: str(saved?.alarm_high),
    enabled: saved?.enabled ?? true,
  };
}

function fromDevice(d: AdminDevice): Draft {
  const t = templates.value.find((x) => x.id === d.template_id);
  const channels: Record<string, ChSet> = {};
  for (const c of t?.channels ?? []) channels[c.key] = chSet(c, d.channels.find((x) => x.key === c.key));
  return {
    id: d.id,
    name: d.name,
    zone: d.zone,
    connection_id: d.connection_id,
    unit_id: String(d.unit_id),
    template_id: d.template_id,
    poll_interval_s: String(d.poll_interval_s),
    enabled: d.enabled,
    channels,
  };
}

function blank(connId: number | null = null, unitId: number | null = null): Draft {
  const t = templates.value[0];
  const d: Draft = {
    id: null,
    name: 'Thiết bị mới',
    zone: '',
    connection_id: connId ?? conns.value[0]?.id ?? null,
    unit_id: unitId != null ? String(unitId) : '',
    template_id: t?.id ?? null,
    poll_interval_s: '10',
    enabled: true,
    channels: {},
  };
  if (t) for (const c of t.channels) d.channels[c.key] = chSet(c);
  return d;
}

/** Đổi mẫu: giữ cài đặt của kênh cùng key, kênh mới lấy mặc định. */
function onTemplate(): void {
  const d = draft.value;
  const t = tpl.value;
  if (!d || !t) return;
  const next: Record<string, ChSet> = {};
  for (const c of t.channels) next[c.key] = d.channels[c.key] ?? chSet(c);
  d.channels = next;
  result.value = null;
}

async function load(selectId?: number | null): Promise<void> {
  const [ds, ts, cs] = await Promise.all([
    api.get<AdminDevice[]>('/api/admin/devices'),
    api.get<Template[]>('/api/admin/templates'),
    api.get<Connection[]>('/api/admin/connections'),
  ]);
  devices.value = ds;
  templates.value = ts;
  conns.value = cs;
  loaded.value = true;
  const want = selectId === undefined ? (draft.value?.id ?? null) : selectId;
  const d = ds.find((x) => x.id === want) ?? ds[0];
  if (d) select(d);
}

function select(d: AdminDevice): void {
  draft.value = fromDevice(d);
  result.value = null;
  clear();
}

function addNew(connId: number | null = null, unitId: number | null = null): void {
  draft.value = blank(connId, unitId);
  result.value = null;
  clear();
}

function tDisplay(c: ChannelDef): [number | null, number | null] {
  return [c.display_min ?? c.min, c.display_max ?? c.max];
}

/** Thang và ngưỡng đang nhập cho thanh xem trước; ô sai định dạng thì bỏ qua. */
function preview(c: ChannelDef): { display_min: number | null; display_max: number | null; alarm_low: number | null; alarm_high: number | null } {
  const s = draft.value?.channels[c.key];
  const p = (v: string | undefined): number | null => {
    const n = parseNum(v ?? '');
    return n == null || Number.isNaN(n) ? null : n;
  };
  const [lo, hi] = tDisplay(c);
  return { display_min: p(s?.display_min) ?? lo, display_max: p(s?.display_max) ?? hi, alarm_low: p(s?.alarm_low), alarm_high: p(s?.alarm_high) };
}

function liveOf(key: string): AdminDevice['channels'][number] | null {
  const d = current.value;
  if (!d || d.template_id !== draft.value?.template_id) return null;
  return d.channels.find((c) => c.key === key) ?? null;
}

function previewValue(c: ChannelDef): number | null {
  const tr = result.value?.values.find((v) => v.key === c.key);
  if (tr && tr.value != null) return tr.value;
  return liveOf(c.key)?.value ?? null;
}

function toBody(d: Draft): Record<string, unknown> {
  return {
    name: d.name.trim(),
    zone: d.zone.trim(),
    connection_id: d.connection_id,
    unit_id: reqNum(d.unit_id, 'unit_id', true),
    template_id: d.template_id,
    poll_interval_s: reqNum(d.poll_interval_s, 'poll_interval_s', true),
    enabled: d.enabled,
    channels: Object.entries(d.channels).map(([key, s]) => ({
      key,
      label: s.label.trim() || null,
      display_min: num(s.display_min, `channels.${key}.display_min`),
      display_max: num(s.display_max, `channels.${key}.display_max`),
      alarm_low: num(s.alarm_low, `channels.${key}.alarm_low`),
      alarm_high: num(s.alarm_high, `channels.${key}.alarm_high`),
      enabled: s.enabled,
    })),
  };
}

async function save(): Promise<void> {
  const d = draft.value;
  if (!d) return;
  clear();
  busy.save = true;
  try {
    const body = toBody(d);
    const saved = d.id == null ? await api.post<AdminDevice>('/api/admin/devices', body) : await api.patch<AdminDevice>(`/api/admin/devices/${d.id}`, body);
    toast(d.id == null ? `Đã thêm ${saved.name}; collector bắt đầu đọc trong vài giây` : `Đã lưu ${saved.name}`);
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
  const ok = await confirmDialog(
    'Xóa thiết bị',
    `Xóa “${d.name}”? Thiết bị ẩn khỏi danh sách và ngừng đọc; dữ liệu lịch sử vẫn giữ nguyên để xem biểu đồ và xuất CSV.`,
    'Xóa thiết bị',
    true,
  );
  if (!ok) return;
  busy.del = true;
  const r = await attempt(() => api.del(`/api/admin/devices/${d.id}`));
  busy.del = false;
  if (r) {
    toast(`Đã xóa ${d.name}`);
    draft.value = null;
    await load(null);
  }
}

async function testRead(): Promise<void> {
  const d = draft.value;
  if (!d) return;
  clear();
  busy.test = true;
  try {
    result.value = await api.post<TestReadResult>('/api/admin/devices/test-read', {
      connection_id: d.connection_id,
      unit_id: reqNum(d.unit_id, 'unit_id', true),
      template_id: d.template_id,
    });
  } catch (e) {
    fail(e);
  } finally {
    busy.test = false;
  }
}

const hlColors = computed(() => {
  const out: Record<string, string> = {};
  (tpl.value?.channels ?? []).forEach((c, i) => (out[c.key] = HL_COLORS[i % HL_COLORS.length]));
  return out;
});

function stateOf(d: AdminDevice): { dot: string; text: string } {
  if (!d.enabled) return { dot: 'off', text: 'Đang tắt' };
  if (d.state === 'online') return { dot: '', text: d.last_rtt_ms != null ? `${Math.round(d.last_rtt_ms)} ms` : 'Trực tuyến' };
  if (d.state === 'offline') return { dot: 'err', text: d.since ? `Mất kết nối từ ${fmtWhen(d.since)}` : 'Mất kết nối' };
  return { dot: 'off', text: 'Chưa có dữ liệu' };
}

const QUALITY: Record<string, string> = { good: 'Tốt', sensor_fault: 'Lỗi cảm biến', out_of_range: 'Ngoài phạm vi' };

onMounted(async () => {
  await attempt(() => load());
  // Từ trang Quét bus: ?moi=1&ket-noi=<id>&id=<unit id>
  if (route.query.moi) {
    const cid = Number(route.query['ket-noi']) || null;
    const uid = route.query.id != null ? Number(route.query.id) : null;
    addNew(cid, uid);
  }
});
</script>

<template>
  <div class="col gap-20">
    <div class="page-head">
      <div class="title-block">
        <h1>Thiết bị</h1>
        <div class="page-sub">Mỗi thiết bị là một node Modbus trên một kết nối, đọc theo một mẫu</div>
      </div>
      <button type="button" class="btn primary" :disabled="!conns.length || !templates.length" @click="addNew()"><Icon name="plus" />Thêm thiết bị</button>
    </div>

    <div v-if="!loaded" class="loading"><div class="spinner" role="status" aria-label="Đang tải" /></div>
    <div v-else-if="!conns.length || !templates.length" class="empty">
      <h2>{{ !conns.length ? 'Chưa có kết nối nào' : 'Chưa có mẫu thiết bị nào' }}</h2>
      <p>Thiết bị cần một kết nối (bus RS-485 hoặc Modbus TCP) và một mẫu thiết bị mô tả bảng thanh ghi.</p>
      <RouterLink class="btn primary" :to="!conns.length ? '/quan-tri/ket-noi' : '/quan-tri/mau'">{{ !conns.length ? 'Thêm kết nối' : 'Thêm mẫu' }}</RouterLink>
    </div>
    <div v-else class="split w280">
      <div class="col gap-8">
        <div v-if="!devices.length" class="empty"><h2>Chưa có thiết bị nào</h2><p>Bấm Thêm thiết bị, hoặc quét bus để tìm địa chỉ.</p></div>
        <button v-for="d in devices" :key="d.id" type="button" class="list-card" :aria-current="d.id === draft?.id" @click="select(d)">
          <span class="row gap-8"><span class="dot" :class="stateOf(d).dot" /><span class="title grow ellipsis">{{ d.name }}</span></span>
          <span class="meta">{{ d.zone || 'Chưa đặt khu vực' }} · {{ d.connection_name }} · ID {{ d.unit_id }}</span>
          <span class="meta tn">{{ stateOf(d).text }}</span>
        </button>
      </div>

      <form v-if="draft" class="col gap-16" novalidate @submit.prevent="save">
        <section class="panel">
          <div class="panel-head">
            <h2 class="panel-title">{{ draft.id == null ? 'Thêm thiết bị' : draft.name }}</h2>
            <span v-if="current && current.state === 'offline'" class="badge off"><Icon name="plugOff" />Mất kết nối</span>
          </div>
          <div v-if="current?.last_error" class="banner note sm">
            <Icon name="info" />
            <div>
              Lỗi gần nhất{{ current.last_error_kind ? ` (${ERROR_KIND[current.last_error_kind] ?? current.last_error_kind})` : '' }}
              {{ current.last_error_ts ? `lúc ${fmtDMHM(current.last_error_ts)}` : '' }}: {{ current.last_error }}
            </div>
          </div>
          <div class="form-grid">
            <FormField label="Tên thiết bị" input-id="tb-ten" :error="errors.name">
              <input id="tb-ten" v-model="draft.name" data-field="name" class="input" :class="{ invalid: errors.name }" maxlength="60" />
            </FormField>
            <FormField label="Khu vực" input-id="tb-kv" :error="errors.zone" hint="Thẻ trên Tổng quan nhóm theo khu vực">
              <input id="tb-kv" v-model="draft.zone" data-field="zone" class="input" maxlength="40" placeholder="Ví dụ Nhà kính 1" />
            </FormField>
            <FormField label="Kết nối" input-id="tb-kn" :error="errors.connection_id" :hint="conn ? connSummary(conn) : ''">
              <select id="tb-kn" v-model="draft.connection_id" data-field="connection_id" class="input">
                <option v-for="c in conns" :key="c.id" :value="c.id">{{ c.name }} ({{ c.type === 'rtu' ? 'RTU' : 'TCP' }})</option>
              </select>
            </FormField>
            <FormField
              label="Unit ID"
              input-id="tb-id"
              :error="errors.unit_id"
              :hint="conn?.type === 'rtu' ? 'Từ 1 đến 247, không trùng trên cùng bus' : 'Từ 0 đến 255; gateway dùng để chọn node phía sau'"
            >
              <input
                id="tb-id"
                v-model="draft.unit_id"
                data-field="unit_id"
                class="input tn"
                :class="{ invalid: errors.unit_id }"
                inputmode="numeric"
              />
            </FormField>
            <FormField label="Mẫu thiết bị" input-id="tb-mau" :error="errors.template_id">
              <select id="tb-mau" v-model="draft.template_id" data-field="template_id" class="input" @change="onTemplate">
                <option v-for="t in templates" :key="t.id" :value="t.id">{{ t.name }}</option>
              </select>
            </FormField>
            <FormField label="Chu kỳ đọc" input-id="tb-ck" :error="errors.poll_interval_s">
              <div class="affix" :class="{ invalid: errors.poll_interval_s }">
                <input id="tb-ck" v-model="draft.poll_interval_s" data-field="poll_interval_s" class="tn" inputmode="numeric" /><span>giây</span>
              </div>
            </FormField>
            <div class="field span-2">
              <label class="check"><input v-model="draft.enabled" type="checkbox" />Đang đọc (bỏ chọn để tạm ngừng mà không xóa)</label>
            </div>
          </div>
        </section>

        <section v-if="tpl" class="panel">
          <div class="panel-head">
            <h2 class="panel-title sm">Kênh đo</h2>
            <span class="small muted">Ô thang để trống dùng thang mặc định của mẫu (chữ mờ)</span>
          </div>
          <div v-for="c in tpl.channels" :key="c.key" class="col gap-10" style="padding-top: 14px; border-top: 1px solid var(--divider)">
            <div class="row wrap gap-8">
              <label class="check sm"><input v-model="draft.channels[c.key].enabled" type="checkbox" :aria-label="`Bật kênh ${c.label}`" /></label>
              <span class="strong">{{ draft.channels[c.key].label || c.label }}</span>
              <span class="mono small muted">{{ c.key }}</span>
              <span v-if="c.estimate" class="badge neutral">Ước tính</span>
              <span class="grow" />
              <span v-if="liveOf(c.key)?.value != null" class="tn fs-13 text-3">
                Hiện tại {{ fmtNum(liveOf(c.key)?.value, liveOf(c.key)?.template.decimals ?? 1) }} {{ c.unit }} · {{ fmtTime(liveOf(c.key)?.ts) }}
              </span>
            </div>
            <div class="form-grid tight" style="grid-template-columns: minmax(0, 1.4fr) repeat(4, minmax(0, 1fr))">
              <FormField label="Nhãn trên thẻ" :input-id="`n-${c.key}`" :error="errors[`channels.${c.key}.label`]" sm>
                <input :id="`n-${c.key}`" v-model="draft.channels[c.key].label" class="input sm" maxlength="40" :placeholder="c.label" />
              </FormField>
              <FormField :label="`Thang từ${c.unit ? ` (${c.unit})` : ''}`" :input-id="`dn-${c.key}`" :error="errors[`channels.${c.key}.display_min`]" sm>
                <input
                  :id="`dn-${c.key}`"
                  v-model="draft.channels[c.key].display_min"
                  :data-field="`channels.${c.key}.display_min`"
                  class="input sm tn"
                  :class="{ invalid: errors[`channels.${c.key}.display_min`] }"
                  :placeholder="fmtAuto(tDisplay(c)[0])"
                />
              </FormField>
              <FormField label="Thang đến" :input-id="`dx-${c.key}`" :error="errors[`channels.${c.key}.display_max`]" sm>
                <input
                  :id="`dx-${c.key}`"
                  v-model="draft.channels[c.key].display_max"
                  :data-field="`channels.${c.key}.display_max`"
                  class="input sm tn"
                  :class="{ invalid: errors[`channels.${c.key}.display_max`] }"
                  :placeholder="fmtAuto(tDisplay(c)[1])"
                />
              </FormField>
              <FormField label="Ngưỡng thấp" :input-id="`al-${c.key}`" :error="errors[`channels.${c.key}.alarm_low`]" sm>
                <input
                  :id="`al-${c.key}`"
                  v-model="draft.channels[c.key].alarm_low"
                  :data-field="`channels.${c.key}.alarm_low`"
                  class="input sm tn"
                  :class="{ invalid: errors[`channels.${c.key}.alarm_low`] }"
                  placeholder="Không"
                />
              </FormField>
              <FormField label="Ngưỡng cao" :input-id="`ah-${c.key}`" :error="errors[`channels.${c.key}.alarm_high`]" sm>
                <input
                  :id="`ah-${c.key}`"
                  v-model="draft.channels[c.key].alarm_high"
                  :data-field="`channels.${c.key}.alarm_high`"
                  class="input sm tn"
                  :class="{ invalid: errors[`channels.${c.key}.alarm_high`] }"
                  placeholder="Không"
                />
              </FormField>
            </div>
            <div style="padding: 4px 14px 0" aria-label="Xem trước thanh dải đo trên HMI">
              <RangeBar :m="preview(c)" :value="previewValue(c)" />
            </div>
          </div>
        </section>

        <section class="panel p20">
          <div class="panel-head">
            <h2 class="panel-title sm">Đọc thử</h2>
            <span class="small muted">Dùng cấu hình đang nhập, chưa cần lưu</span>
            <button type="button" class="btn sm" :class="{ busy: busy.test }" :disabled="busy.test || !draft.connection_id || !draft.template_id" @click="testRead">
              <Icon name="play" />Đọc thử
            </button>
          </div>
          <template v-if="result">
            <div v-if="result.ok" class="banner ok sm">
              <Icon name="check" />
              <div class="tn">
                <span class="strong">Đọc được lúc {{ fmtTime(result.at) }}</span> · phản hồi {{ fmtNum(result.rtt_ms, 0) }} ms qua
                {{ result.requests.length }} request
              </div>
            </div>
            <div v-else-if="result.error" class="banner danger sm" role="alert">
              <Icon name="xCircle" />
              <div class="col gap-4">
                <span
                  ><span class="strong">{{ ERROR_KIND[result.error.kind] ?? result.error.kind }}:</span> {{ result.error.message
                  }}{{ result.error.name ? ` (${result.error.name})` : '' }}</span
                >
                <span>{{ result.error.hint }}</span>
              </div>
            </div>
            <div v-for="(r, i) in result.requests" :key="i" class="frames" style="max-height: none">
              <div class="small muted" style="font-family: var(--font)">
                FC 0{{ r.fc }} · unit {{ r.unit_id }} · thanh ghi {{ r.address }}, {{ r.count }} thanh ghi · {{ fmtNum(r.rtt_ms, 0) }} ms
              </div>
              <div class="fr"><span class="muted">Gửi</span><span>TX</span><span class="hex">{{ r.tx }}</span><span /></div>
              <div class="fr rx">
                <span class="muted">Nhận</span><span>RX</span><span class="hex"><HexFrame :hex="r.rx" :highlights="r.highlights" :colors="hlColors" /></span><span />
              </div>
            </div>
            <div v-if="result.error && (result.error.tx || result.error.rx)" class="frames">
              <div v-if="result.error.tx" class="fr"><span class="muted">Gửi</span><span>TX</span><span class="hex">{{ result.error.tx }}</span><span /></div>
              <div v-if="result.error.rx" class="fr err"><span class="muted">Nhận</span><span>RX</span><span class="hex">{{ result.error.rx }}</span><span /></div>
            </div>
            <div v-if="result.values.length" class="tbl-wrap" style="padding: 0 8px">
              <table class="tbl compact">
                <thead>
                  <tr><th>Kênh</th><th>Thanh ghi</th><th>Thô (hex)</th><th class="num">Giá trị</th><th>Chất lượng</th></tr>
                </thead>
                <tbody>
                  <tr v-for="v in result.values" :key="v.key">
                    <td><span class="row gap-6"><span class="dot" :style="{ background: hlColors[v.key] ?? 'var(--chip)', border: '1px solid var(--border-strong)' }" />{{ v.label }}</span></td>
                    <td class="tn">{{ v.registers }}</td>
                    <td class="mono small">{{ v.raw_hex }}</td>
                    <td class="num tn strong">{{ v.value != null ? `${fmtNum(v.value, v.decimals)} ${v.unit}` : '—' }}</td>
                    <td :class="{ 'hint err': v.quality !== 'good' }">{{ QUALITY[v.quality] ?? v.quality }}{{ v.detail ? ` · ${v.detail}` : '' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
          <div v-else class="small muted">
            Đọc mọi kênh của mẫu ở unit ID đang nhập; hiện thanh ghi thô (hex), giá trị đã giải mã và thời gian phản hồi, hoặc lỗi cụ thể kèm gợi ý.
          </div>
        </section>

        <div class="row wrap" style="gap: 8px">
          <button v-if="draft.id != null" type="button" class="btn danger" :disabled="busy.del" @click="remove">Xóa thiết bị</button>
          <span class="grow" />
          <button type="submit" class="btn primary" :class="{ busy: busy.save }" :disabled="busy.save"><Icon name="save" />Lưu thiết bị</button>
        </div>
      </form>
    </div>
  </div>
</template>

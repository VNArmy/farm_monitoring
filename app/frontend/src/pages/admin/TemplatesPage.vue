<script setup lang="ts">
// Quản trị · Mẫu thiết bị (spec mục 4.4, 8.3): bảng thanh ghi, gợi ý quy đổi địa chỉ 4xxxx/3xxxx, chặn kiểu 32 bit
// thiếu thứ tự byte, cảnh báo 2 kênh chồng lấn thanh ghi; sao chép, nhập và xuất JSON.
import { computed, onMounted, reactive, ref } from 'vue';
import FormField from '../../components/FormField.vue';
import Icon from '../../components/Icon.vue';
import { api, download } from '../../lib/api';
import { BYTE_ORDERS, CATEGORY_NAMES, DTYPES, FieldError, REG_COUNT, addressHint, num, reqNum, str } from '../../lib/admin';
import { fmtDateTime, parseNum } from '../../lib/format';
import type { ChannelDef, Template } from '../../lib/types';
import { attempt, confirmDialog, toast, useFormErrors } from '../../lib/ui';

interface ChDraft {
  uid: number;
  key: string;
  label: string;
  unit: string;
  fc: 3 | 4;
  address: string;
  type: ChannelDef['type'];
  byte_order: ChannelDef['byte_order'];
  scale: string;
  offset: string;
  min: string;
  max: string;
  display_min: string;
  display_max: string;
  invalid_value: string;
  agg: ChannelDef['agg'];
  decimals: string;
  estimate: boolean;
  note: string;
  open: boolean;
}

interface Draft {
  id: number | null;
  name: string;
  category: string;
  address_register: string;
  baud_register: string;
  baud_codes: string;
  channels: ChDraft[];
}

const templates = ref<Template[]>([]);
const loaded = ref(false);
const draft = ref<Draft | null>(null);
const busy = reactive({ save: false, del: false, imp: false });
const fileEl = ref<HTMLInputElement>();
const { errors, clear, fail } = useFormErrors();
let uidSeq = 0;

function chDraft(c: Partial<ChannelDef> = {}): ChDraft {
  return {
    uid: ++uidSeq,
    key: c.key ?? '',
    label: c.label ?? '',
    unit: c.unit ?? '',
    fc: c.fc ?? 4,
    address: str(c.address ?? 0),
    type: c.type ?? 'float32',
    byte_order: c.byte_order ?? (c.type && REG_COUNT[c.type] === 1 ? null : 'ABCD'),
    scale: str(c.scale ?? 1),
    offset: str(c.offset ?? 0),
    min: str(c.min),
    max: str(c.max),
    display_min: str(c.display_min),
    display_max: str(c.display_max),
    invalid_value: str(c.invalid_value),
    agg: c.agg ?? 'mean',
    decimals: str(c.decimals),
    estimate: c.estimate ?? false,
    note: c.note ?? '',
    open: false,
  };
}

function fromTemplate(t: Template): Draft {
  return {
    id: t.id,
    name: t.name,
    category: t.category,
    address_register: str(t.address_register),
    baud_register: str(t.baud_register),
    baud_codes: t.baud_codes ? Object.entries(t.baud_codes).map(([b, c]) => `${b}=${c}`).join(', ') : '',
    channels: t.channels.map((c) => chDraft(c)),
  };
}

function blank(): Draft {
  return {
    id: null,
    name: 'Mẫu mới',
    category: 'other',
    address_register: '',
    baud_register: '',
    baud_codes: '',
    channels: [{ ...chDraft({ key: 'value', label: 'Giá trị' }), open: true }],
  };
}

function toBody(d: Draft): Record<string, unknown> {
  let baud_codes: Record<string, number> | null = null;
  if (d.baud_codes.trim()) {
    baud_codes = {};
    for (const part of d.baud_codes.split(/[,;\n]/)) {
      const m = /^\s*(\d+)\s*[=:]\s*(\d+)\s*$/.exec(part);
      if (!part.trim()) continue;
      if (!m) throw new FieldError('baud_codes', 'Ghi theo dạng 9600=2, 4800=1');
      baud_codes[m[1]] = Number(m[2]);
    }
  }
  const channels = d.channels.map((c, i) => {
    const f = `channels.${i}`;
    const is32 = REG_COUNT[c.type] === 2;
    if (is32 && !c.byte_order) {
      c.open = true;
      throw new FieldError(`${f}.byte_order`, 'Kiểu 32 bit cần chọn thứ tự byte');
    }
    try {
      return {
        key: c.key.trim(),
        label: c.label.trim(),
        unit: c.unit.trim(),
        fc: c.fc,
        address: reqNum(c.address, `${f}.address`, true),
        type: c.type,
        byte_order: is32 ? c.byte_order : null,
        scale: reqNum(c.scale, `${f}.scale`),
        offset: reqNum(c.offset, `${f}.offset`),
        min: num(c.min, `${f}.min`),
        max: num(c.max, `${f}.max`),
        display_min: num(c.display_min, `${f}.display_min`),
        display_max: num(c.display_max, `${f}.display_max`),
        invalid_value: num(c.invalid_value, `${f}.invalid_value`, { int: true }),
        agg: c.agg,
        decimals: num(c.decimals, `${f}.decimals`, { int: true }),
        estimate: c.estimate,
        note: c.note.trim(),
      };
    } catch (e) {
      c.open = true;
      throw e;
    }
  });
  return {
    name: d.name.trim(),
    category: d.category,
    address_register: num(d.address_register, 'address_register', { int: true }),
    baud_register: num(d.baud_register, 'baud_register', { int: true }),
    baud_codes,
    channels,
  };
}

// Lỗi server chỉ tới "channels.<i>.<trường>": mở kênh đó để thấy ô lỗi.
function failAndOpen(e: unknown): void {
  const field = e instanceof Error && 'field' in e ? String((e as { field: unknown }).field ?? '') : '';
  const m = /^channels\.(\d+)\./.exec(field);
  if (m && draft.value?.channels[Number(m[1])]) draft.value.channels[Number(m[1])].open = true;
  fail(e);
}

/** Kênh chồng lấn thanh ghi (cùng FC, dải địa chỉ giao nhau): cảnh báo ngay khi đang nhập. */
const overlaps = computed(() => {
  const d = draft.value;
  if (!d) return [];
  const items = d.channels
    .map((c) => ({ c, a: parseNum(c.address), n: REG_COUNT[c.type] }))
    .filter((x) => x.a != null && Number.isFinite(x.a)) as { c: ChDraft; a: number; n: number }[];
  items.sort((x, y) => x.c.fc - y.c.fc || x.a - y.a);
  const out: string[] = [];
  for (let i = 0; i < items.length; i++) {
    for (let j = i + 1; j < items.length; j++) {
      const x = items[i];
      const y = items[j];
      if (y.c.fc !== x.c.fc || y.a >= x.a + x.n) break;
      out.push(`${x.c.key || `kênh ${i + 1}`} và ${y.c.key || `kênh ${j + 1}`} cùng dùng thanh ghi ${y.a} (FC 0${x.c.fc})`);
    }
  }
  return out;
});

function regText(c: ChDraft): string {
  const a = parseNum(c.address);
  if (a == null || Number.isNaN(a)) return '';
  const n = REG_COUNT[c.type];
  return n === 2 ? `${a}–${a + 1}` : `${a}`;
}

async function load(selectId?: number | null): Promise<void> {
  templates.value = await api.get<Template[]>('/api/admin/templates');
  loaded.value = true;
  const want = selectId === undefined ? (draft.value?.id ?? null) : selectId;
  const t = templates.value.find((x) => x.id === want) ?? templates.value[0];
  if (t) select(t);
}

function select(t: Template): void {
  draft.value = fromTemplate(t);
  clear();
}

function addNew(): void {
  draft.value = blank();
  clear();
}

function copy(): void {
  const d = draft.value;
  if (!d) return;
  draft.value = { ...d, id: null, name: `${d.name} (bản sao)`.slice(0, 60), channels: d.channels.map((c) => ({ ...c, uid: ++uidSeq })) };
  clear();
  toast('Đã tạo bản sao, sửa rồi bấm Lưu');
}

function addChannel(): void {
  const d = draft.value;
  if (!d) return;
  const last = d.channels[d.channels.length - 1];
  const next = last ? (parseNum(last.address) ?? 0) + REG_COUNT[last.type] : 0;
  d.channels.push({ ...chDraft({ key: `kenh_${d.channels.length + 1}`, label: `Kênh ${d.channels.length + 1}`, fc: last?.fc ?? 4, address: next }), open: true });
}

function move(i: number, delta: number): void {
  const chs = draft.value?.channels;
  if (!chs) return;
  const j = i + delta;
  if (j < 0 || j >= chs.length) return;
  [chs[i], chs[j]] = [chs[j], chs[i]];
}

function removeChannel(i: number): void {
  draft.value?.channels.splice(i, 1);
}

function onType(c: ChDraft): void {
  if (REG_COUNT[c.type] === 1) c.byte_order = null;
  else if (!c.byte_order) c.byte_order = 'ABCD';
}

async function save(): Promise<void> {
  const d = draft.value;
  if (!d) return;
  clear();
  busy.save = true;
  try {
    const body = toBody(d);
    const t = d.id == null ? await api.post<Template>('/api/admin/templates', body) : await api.patch<Template>(`/api/admin/templates/${d.id}`, body);
    toast(d.id == null ? `Đã thêm mẫu ${t.name}` : `Đã lưu mẫu ${t.name}; dữ liệu đọc từ giờ theo cấu hình mới`);
    await load(t.id);
  } catch (e) {
    failAndOpen(e);
  } finally {
    busy.save = false;
  }
}

async function remove(): Promise<void> {
  const d = draft.value;
  if (!d || d.id == null) return;
  if (!(await confirmDialog('Xóa mẫu', `Xóa mẫu “${d.name}”?`, 'Xóa', true))) return;
  busy.del = true;
  const r = await attempt(() => api.del(`/api/admin/templates/${d.id}`));
  busy.del = false;
  if (r) {
    toast(`Đã xóa mẫu ${d.name}`);
    draft.value = null;
    await load(null);
  }
}

async function onImport(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (!file) return;
  busy.imp = true;
  try {
    let body: unknown;
    try {
      body = JSON.parse(await file.text());
    } catch {
      throw new Error('Tệp không phải JSON hợp lệ');
    }
    const created = await api.post<Template[]>('/api/admin/templates/import', body);
    toast(`Đã nhập ${created.length} mẫu`);
    await load(created[0]?.id);
  } catch (err) {
    fail(err);
  } finally {
    busy.imp = false;
  }
}

const current = computed(() => templates.value.find((t) => t.id === draft.value?.id) ?? null);

onMounted(() => void attempt(() => load()));
</script>

<template>
  <div class="col gap-20">
    <div class="page-head">
      <div class="title-block">
        <h1>Mẫu thiết bị</h1>
        <div class="page-sub">Bảng thanh ghi của từng loại cảm biến; thiết bị cùng loại dùng chung một mẫu</div>
      </div>
      <div class="row wrap gap-8">
        <input ref="fileEl" type="file" accept="application/json,.json" hidden @change="onImport" />
        <button type="button" class="btn" :class="{ busy: busy.imp }" @click="fileEl?.click()"><Icon name="upload" />Nhập JSON</button>
        <button type="button" class="btn primary" @click="addNew"><Icon name="plus" />Thêm mẫu</button>
      </div>
    </div>

    <div v-if="!loaded" class="loading"><div class="spinner" role="status" aria-label="Đang tải" /></div>
    <div v-else class="split w280">
      <div class="col gap-8">
        <div v-if="!templates.length" class="empty"><h2>Chưa có mẫu nào</h2><p>Thêm mẫu hoặc nhập từ tệp JSON.</p></div>
        <button v-for="t in templates" :key="t.id" type="button" class="list-card" :aria-current="t.id === draft?.id" @click="select(t)">
          <span class="title">{{ t.name }}</span>
          <span class="meta">{{ CATEGORY_NAMES[t.category] ?? t.category }} · {{ t.channels.length }} kênh · {{ t.devices.length }} thiết bị</span>
        </button>
      </div>

      <form v-if="draft" class="panel" novalidate @submit.prevent="save">
        <div class="panel-head">
          <h2 class="panel-title">{{ draft.id == null ? 'Mẫu mới' : draft.name }}</h2>
          <template v-if="draft.id != null">
            <button type="button" class="btn sm" @click="download(`/api/admin/templates/${draft.id}?download=1`)"><Icon name="download" />Xuất JSON</button>
            <button type="button" class="btn sm" @click="copy"><Icon name="copy" />Sao chép</button>
          </template>
        </div>
        <div v-if="current?.devices.length" class="banner note sm">
          <Icon name="info" />
          <div>
            Đang dùng cho {{ current.devices.map((d) => d.name).join(', ') }}. Sửa mẫu chỉ ảnh hưởng dữ liệu đọc sau đó; nhật ký ghi lại giá trị
            trước và sau.
          </div>
        </div>

        <div class="form-grid">
          <FormField label="Tên mẫu" input-id="m-ten" :error="errors.name">
            <input id="m-ten" v-model="draft.name" data-field="name" class="input" :class="{ invalid: errors.name }" maxlength="60" />
          </FormField>
          <FormField label="Nhóm" input-id="m-nhom" :error="errors.category">
            <select id="m-nhom" v-model="draft.category" data-field="category" class="input">
              <option v-for="(n, k) in CATEGORY_NAMES" :key="k" :value="k">{{ n }}</option>
            </select>
          </FormField>
        </div>

        <div class="col gap-12">
          <div class="row">
            <h3 class="panel-title sm grow">Bảng thanh ghi</h3>
            <span class="small muted">{{ draft.channels.length }} kênh</span>
          </div>
          <div v-if="overlaps.length" class="banner warn sm" role="status">
            <Icon name="warn" />
            <div><span class="strong">Chồng lấn thanh ghi:</span> {{ overlaps.join('; ') }}.</div>
          </div>

          <div v-for="(c, i) in draft.channels" :key="c.uid" class="panel p22" style="gap: 12px; border-color: var(--border-strong)">
            <div class="row gap-8">
              <button type="button" class="icon-btn" :aria-expanded="c.open" :aria-label="c.open ? 'Thu gọn kênh' : 'Mở kênh'" @click="c.open = !c.open">
                <Icon :name="c.open ? 'up' : 'down'" />
              </button>
              <div class="col grow" style="min-width: 0">
                <span class="strong ellipsis">{{ c.label || 'Kênh chưa đặt tên' }} <span class="mono small muted">{{ c.key }}</span></span>
                <span class="small muted tn">
                  FC 0{{ c.fc }} · thanh ghi {{ regText(c) }} · {{ c.type }}{{ c.byte_order && REG_COUNT[c.type] === 2 ? ` ${c.byte_order}` : '' }}{{
                    c.unit ? ` · ${c.unit}` : ''
                  }}
                </span>
              </div>
              <button type="button" class="icon-btn" aria-label="Lên trên" :disabled="i === 0" @click="move(i, -1)"><Icon name="arrowUp" /></button>
              <button type="button" class="icon-btn" aria-label="Xuống dưới" :disabled="i === draft.channels.length - 1" @click="move(i, 1)">
                <Icon name="arrowDown" />
              </button>
              <button type="button" class="icon-btn" aria-label="Bỏ kênh" :disabled="draft.channels.length === 1" @click="removeChannel(i)">
                <Icon name="trash" />
              </button>
            </div>

            <div v-show="c.open" class="col gap-12">
              <div class="form-grid tight" style="grid-template-columns: repeat(4, minmax(0, 1fr))">
                <FormField label="Key" :input-id="`k-${c.uid}`" :error="errors[`channels.${i}.key`]" sm>
                  <input :id="`k-${c.uid}`" v-model="c.key" :data-field="`channels.${i}.key`" class="input sm mono" :class="{ invalid: errors[`channels.${i}.key`] }" />
                </FormField>
                <FormField label="Nhãn" :input-id="`l-${c.uid}`" :error="errors[`channels.${i}.label`]" sm>
                  <input :id="`l-${c.uid}`" v-model="c.label" :data-field="`channels.${i}.label`" class="input sm" maxlength="40" />
                </FormField>
                <FormField label="Đơn vị" :input-id="`u-${c.uid}`" sm>
                  <input :id="`u-${c.uid}`" v-model="c.unit" class="input sm" maxlength="16" />
                </FormField>
                <FormField label="Function code" :input-id="`f-${c.uid}`" sm>
                  <select :id="`f-${c.uid}`" v-model.number="c.fc" class="input sm">
                    <option :value="4">04 · Input register</option>
                    <option :value="3">03 · Holding register</option>
                  </select>
                </FormField>
                <FormField
                  label="Địa chỉ"
                  :input-id="`a-${c.uid}`"
                  :error="errors[`channels.${i}.address`]"
                  :hint="addressHint(parseNum(c.address), c.fc) ?? 'Địa chỉ giao thức, đếm từ 0'"
                  sm
                >
                  <input
                    :id="`a-${c.uid}`"
                    v-model="c.address"
                    :data-field="`channels.${i}.address`"
                    class="input sm tn"
                    :class="{ invalid: errors[`channels.${i}.address`] }"
                    inputmode="numeric"
                  />
                </FormField>
                <FormField label="Kiểu dữ liệu" :input-id="`t-${c.uid}`" sm>
                  <select :id="`t-${c.uid}`" v-model="c.type" class="input sm" @change="onType(c)">
                    <option v-for="t in DTYPES" :key="t" :value="t">{{ t }}</option>
                  </select>
                </FormField>
                <FormField label="Thứ tự byte" :input-id="`b-${c.uid}`" :error="errors[`channels.${i}.byte_order`]" sm>
                  <select
                    :id="`b-${c.uid}`"
                    v-model="c.byte_order"
                    :data-field="`channels.${i}.byte_order`"
                    class="input sm"
                    :class="{ invalid: errors[`channels.${i}.byte_order`] }"
                    :disabled="REG_COUNT[c.type] === 1"
                  >
                    <option :value="null" disabled>{{ REG_COUNT[c.type] === 1 ? 'Không cần (16 bit)' : 'Chọn…' }}</option>
                    <option v-for="b in BYTE_ORDERS" :key="b" :value="b">{{ b }}</option>
                  </select>
                </FormField>
                <FormField label="Cách gộp" :input-id="`g-${c.uid}`" sm>
                  <select :id="`g-${c.uid}`" v-model="c.agg" class="input sm">
                    <option value="mean">Trung bình</option>
                    <option value="circular_mean">Trung bình góc (hướng gió)</option>
                  </select>
                </FormField>
                <FormField label="Hệ số" :input-id="`s-${c.uid}`" :error="errors[`channels.${i}.scale`]" hint="giá trị = thô × hệ số + offset" sm>
                  <input :id="`s-${c.uid}`" v-model="c.scale" :data-field="`channels.${i}.scale`" class="input sm tn" :class="{ invalid: errors[`channels.${i}.scale`] }" />
                </FormField>
                <FormField label="Offset" :input-id="`o-${c.uid}`" :error="errors[`channels.${i}.offset`]" sm>
                  <input :id="`o-${c.uid}`" v-model="c.offset" :data-field="`channels.${i}.offset`" class="input sm tn" />
                </FormField>
                <FormField label="Mã lỗi cảm biến" :input-id="`e-${c.uid}`" :error="errors[`channels.${i}.invalid_value`]" hint="Giá trị thô node báo khi cảm biến hỏng, ví dụ -32768" sm>
                  <input
                    :id="`e-${c.uid}`"
                    v-model="c.invalid_value"
                    :data-field="`channels.${i}.invalid_value`"
                    class="input sm tn"
                    placeholder="Không có"
                  />
                </FormField>
                <FormField label="Số chữ số lẻ" :input-id="`d-${c.uid}`" :error="errors[`channels.${i}.decimals`]" sm>
                  <input :id="`d-${c.uid}`" v-model="c.decimals" :data-field="`channels.${i}.decimals`" class="input sm tn" placeholder="Tự động" />
                </FormField>
              </div>

              <div class="form-grid tight" style="grid-template-columns: repeat(4, minmax(0, 1fr))">
                <FormField label="Hợp lệ từ" :input-id="`mn-${c.uid}`" :error="errors[`channels.${i}.min`]" sm>
                  <input :id="`mn-${c.uid}`" v-model="c.min" :data-field="`channels.${i}.min`" class="input sm tn" />
                </FormField>
                <FormField label="Hợp lệ đến" :input-id="`mx-${c.uid}`" :error="errors[`channels.${i}.max`]" sm>
                  <input :id="`mx-${c.uid}`" v-model="c.max" :data-field="`channels.${i}.max`" class="input sm tn" :class="{ invalid: errors[`channels.${i}.max`] }" />
                </FormField>
                <FormField label="Thang hiển thị từ" :input-id="`dn-${c.uid}`" :error="errors[`channels.${i}.display_min`]" sm>
                  <input
                    :id="`dn-${c.uid}`"
                    v-model="c.display_min"
                    :data-field="`channels.${i}.display_min`"
                    class="input sm tn"
                    :class="{ invalid: errors[`channels.${i}.display_min`] }"
                    :placeholder="c.min || ''"
                  />
                </FormField>
                <FormField label="Thang hiển thị đến" :input-id="`dx-${c.uid}`" :error="errors[`channels.${i}.display_max`]" sm>
                  <input
                    :id="`dx-${c.uid}`"
                    v-model="c.display_max"
                    :data-field="`channels.${i}.display_max`"
                    class="input sm tn"
                    :class="{ invalid: errors[`channels.${i}.display_max`] }"
                    :placeholder="c.max || ''"
                  />
                </FormField>
                <div class="hint span-2" style="grid-column: 1 / -1">
                  Phạm vi hợp lệ: giá trị ngoài khoảng này bị gắn cờ “Ngoài phạm vi” (thường do nhiễu hoặc cảm biến hỏng). Thang hiển thị: dải
                  vẽ thanh đo trên HMI và thiết bị; bỏ trống thì dùng phạm vi hợp lệ. Mỗi thiết bị có thể đặt thang riêng.
                </div>
              </div>

              <div class="row wrap gap-16">
                <label class="check sm"><input v-model="c.estimate" type="checkbox" />Giá trị ước tính (ví dụ CO2 từ MQ135)</label>
                <FormField label="Ghi chú" :input-id="`n-${c.uid}`" sm style="flex: 1 1 240px">
                  <input :id="`n-${c.uid}`" v-model="c.note" class="input sm" maxlength="60" />
                </FormField>
              </div>
            </div>
          </div>
          <button type="button" class="btn dashed" style="align-self: flex-start" :disabled="draft.channels.length >= 32" @click="addChannel">
            <Icon name="plus" />Thêm kênh
          </button>
        </div>

        <div class="col gap-12">
          <h3 class="panel-title sm">Thanh ghi cấu hình (FC 06)</h3>
          <div class="form-grid tight" style="grid-template-columns: repeat(3, minmax(0, 1fr))">
            <FormField label="Thanh ghi địa chỉ" input-id="m-ar" :error="errors.address_register" hint="Để trống nếu không đổi được địa chỉ qua Modbus" sm>
              <input id="m-ar" v-model="draft.address_register" data-field="address_register" class="input sm tn" />
            </FormField>
            <FormField label="Thanh ghi baud rate" input-id="m-br" :error="errors.baud_register" sm>
              <input id="m-br" v-model="draft.baud_register" data-field="baud_register" class="input sm tn" />
            </FormField>
            <FormField label="Mã baud" input-id="m-bc" :error="errors.baud_codes" hint="Ví dụ 4800=1, 9600=2" sm>
              <input id="m-bc" v-model="draft.baud_codes" data-field="baud_codes" class="input sm mono" :class="{ invalid: errors.baud_codes }" />
            </FormField>
          </div>
        </div>

        <div class="row wrap" style="gap: 8px">
          <button
            v-if="draft.id != null"
            type="button"
            class="btn danger"
            :disabled="busy.del || !!current?.devices.length"
            :title="current?.devices.length ? 'Còn thiết bị dùng mẫu này' : undefined"
            @click="remove"
          >
            Xóa mẫu
          </button>
          <span v-if="current" class="small muted">Sửa lần cuối {{ fmtDateTime(current.updated_at) }}</span>
          <span class="grow" />
          <button type="submit" class="btn primary" :class="{ busy: busy.save }" :disabled="busy.save"><Icon name="save" />Lưu mẫu</button>
        </div>
      </form>
    </div>
  </div>
</template>

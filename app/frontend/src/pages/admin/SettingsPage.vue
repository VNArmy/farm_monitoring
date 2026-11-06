<script setup lang="ts">
// Quản trị · Cài đặt (spec mục 8.7): tên site, múi giờ, thời gian lưu dữ liệu thô, lịch backup; màn hình HMI (bố cục,
// thẻ và thứ tự, cho xem biểu đồ, tải lại màn); nhật ký thay đổi lọc theo người dùng và đối tượng.
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import FormField from '../../components/FormField.vue';
import Icon from '../../components/Icon.vue';
import { api, download, qs } from '../../lib/api';
import { reqNum } from '../../lib/admin';
import { fmtBytes, fmtDateTime, fmtWhen } from '../../lib/format';
import { attempt, confirmDialog, toast, useFormErrors } from '../../lib/ui';

interface Settings {
  site_name: string;
  timezone: string;
  public_url: string;
  raw_retention_days: number;
  backup_time: string;
  backup_keep: number;
  timezones: string[];
  last_backup: { ts: number; file: string; size: number } | null;
  backup_dir: string;
}

interface HmiCardItem {
  id: string;
  visible: boolean;
  label: string;
  sub: string;
}

interface HmiAdmin {
  layout: 'cards' | 'overview';
  cards: HmiCardItem[];
  allow_charts: boolean;
  lan_url: string;
  url: string;
  status: { online: boolean; connected_since: number | null; width: number | null; height: number | null; kiosk: boolean };
}

interface AuditRow {
  id: number;
  ts: number;
  username: string | null;
  action: string;
  entity: string;
  entity_id: number | null;
  before: string | null;
  after: string | null;
  summary: string | null;
}

const ENTITY_NAMES: Record<string, string> = {
  connection: 'Kết nối',
  template: 'Mẫu thiết bị',
  device: 'Thiết bị',
  user: 'Người dùng',
  settings: 'Cài đặt',
  hmi: 'Màn hình HMI',
  seed: 'Cấu hình ban đầu',
};
const ACTION_NAMES: Record<string, string> = {
  create: 'Thêm',
  update: 'Sửa',
  delete: 'Xóa',
  import: 'Nhập',
  password: 'Đổi mật khẩu',
  reset_password: 'Đặt lại mật khẩu',
  set_address: 'Đổi địa chỉ',
  backup: 'Backup',
  reload: 'Tải lại',
};

// --- Cài đặt chung --------------------------------------------------------------------------
const s = ref<Settings | null>(null);
const form = reactive({ site_name: '', timezone: '', public_url: '', raw_retention_days: '', backup_time: '', backup_keep: '' });
const busy = reactive({ save: false, backup: false, hmi: false, reload: false, audit: false });
const { errors, clear, fail } = useFormErrors();

function fill(x: Settings): void {
  s.value = x;
  Object.assign(form, {
    site_name: x.site_name,
    timezone: x.timezone,
    public_url: x.public_url ?? '',
    raw_retention_days: String(x.raw_retention_days),
    backup_time: x.backup_time,
    backup_keep: String(x.backup_keep),
  });
}

async function saveSettings(): Promise<void> {
  clear();
  busy.save = true;
  try {
    fill(
      await api.put<Settings>('/api/admin/settings', {
        site_name: form.site_name.trim(),
        timezone: form.timezone,
        public_url: form.public_url.trim(),
        raw_retention_days: reqNum(form.raw_retention_days, 'raw_retention_days', true),
        backup_time: form.backup_time,
        backup_keep: reqNum(form.backup_keep, 'backup_keep', true),
      }),
    );
    toast('Đã lưu cài đặt');
    void loadAudit(true);
  } catch (e) {
    fail(e);
  } finally {
    busy.save = false;
  }
}

async function backupNow(): Promise<void> {
  busy.backup = true;
  const r = await attempt(() => api.post<{ ts: number; file: string; size: number }>('/api/admin/backup'));
  busy.backup = false;
  if (r && s.value) {
    s.value.last_backup = r;
    toast(`Đã backup ${r.file} (${fmtBytes(r.size)})`);
    void loadAudit(true);
  }
}

// --- Màn hình HMI --------------------------------------------------------------------------
const hmi = ref<HmiAdmin | null>(null);
const hmiDirty = ref(false);
const visibleCount = computed(() => hmi.value?.cards.filter((c) => c.visible).length ?? 0);

async function loadHmi(): Promise<void> {
  if (hmiDirty.value) {
    // Đang sửa: chỉ cập nhật trạng thái màn, giữ thay đổi chưa lưu.
    const r = await api.get<HmiAdmin>('/api/admin/hmi');
    if (hmi.value) hmi.value.status = r.status;
    return;
  }
  hmi.value = await api.get<HmiAdmin>('/api/admin/hmi');
}

function moveCard(i: number, d: number): void {
  const cards = hmi.value?.cards;
  if (!cards) return;
  const j = i + d;
  if (j < 0 || j >= cards.length) return;
  [cards[i], cards[j]] = [cards[j], cards[i]];
  hmiDirty.value = true;
}

async function saveHmi(): Promise<void> {
  const h = hmi.value;
  if (!h) return;
  busy.hmi = true;
  const r = await attempt(() =>
    api.put<HmiAdmin>('/api/admin/hmi', {
      layout: h.layout,
      allow_charts: h.allow_charts,
      cards: h.cards.map((c) => ({ id: c.id, visible: c.visible })),
    }),
  );
  busy.hmi = false;
  if (r) {
    hmi.value = r;
    hmiDirty.value = false;
    toast('Đã lưu; màn HMI áp dụng ngay, không cần tải lại');
    void loadAudit(true);
  }
}

async function reloadHmi(): Promise<void> {
  if (!(await confirmDialog('Tải lại màn hình HMI', 'Trang trên màn HDMI của Datalogger sẽ tải lại trong vài giây.', 'Tải lại'))) return;
  busy.reload = true;
  const r = await attempt(() => api.post('/api/admin/hmi/reload'));
  busy.reload = false;
  if (r) {
    toast('Đã gửi lệnh tải lại tới màn HMI');
    void loadAudit(true);
  }
}

// --- Nhật ký -------------------------------------------------------------------------------
const audit = reactive({ rows: [] as AuditRow[], users: [] as string[], entities: [] as string[], user: '', entity: '', more: false, open: null as number | null });
const PAGE = 50;

async function loadAudit(reset = false): Promise<void> {
  busy.audit = true;
  try {
    const before = reset ? undefined : audit.rows[audit.rows.length - 1]?.id;
    const r = await api.get<{ rows: AuditRow[]; users: string[]; entities: string[] }>(
      `/api/admin/audit-log?${qs({ user: audit.user, entity: audit.entity, limit: PAGE, before })}`,
    );
    audit.rows = reset ? r.rows : [...audit.rows, ...r.rows];
    audit.users = r.users;
    audit.entities = r.entities;
    audit.more = r.rows.length === PAGE;
  } catch (e) {
    toast(e instanceof Error ? e.message : String(e), 'err');
  } finally {
    busy.audit = false;
  }
}

function pretty(json: string | null): string {
  if (!json) return '—';
  try {
    return JSON.stringify(JSON.parse(json), null, 2);
  } catch {
    return json;
  }
}

let timer: ReturnType<typeof setInterval> | undefined;
onMounted(async () => {
  await attempt(async () => {
    const [x] = await Promise.all([api.get<Settings>('/api/admin/settings'), loadHmi(), loadAudit(true)]);
    fill(x);
  });
  timer = setInterval(() => void loadHmi().catch(() => undefined), 10_000);
});
onBeforeUnmount(() => clearInterval(timer));
</script>

<template>
  <div class="col gap-20">
    <div class="page-head">
      <div class="title-block">
        <h1>Cài đặt</h1>
        <div class="page-sub">Thông tin site, lưu trữ và backup, màn hình HMI, nhật ký thay đổi</div>
      </div>
    </div>

    <div v-if="!s" class="loading"><div class="spinner" role="status" aria-label="Đang tải" /></div>
    <template v-else>
      <div class="split even">
        <form class="panel" novalidate @submit.prevent="saveSettings">
          <h2 class="panel-title">Site và lưu trữ</h2>
          <div class="form-grid">
            <FormField label="Tên site" input-id="c-site" :error="errors.site_name" span2>
              <input id="c-site" v-model="form.site_name" data-field="site_name" class="input" :class="{ invalid: errors.site_name }" maxlength="60" />
            </FormField>
            <FormField label="Múi giờ hiển thị" input-id="c-tz" :error="errors.timezone" hint="Dữ liệu lưu theo UTC; chỉ đổi cách hiển thị">
              <select id="c-tz" v-model="form.timezone" data-field="timezone" class="input">
                <option v-for="z in s.timezones" :key="z" :value="z">{{ z }}</option>
              </select>
            </FormField>
            <FormField
              label="Địa chỉ web app"
              input-id="c-url"
              :error="errors.public_url"
              hint="Hiện trên mã QR của màn HMI; để trống thì dùng địa chỉ LAN của Datalogger"
            >
              <input
                id="c-url"
                v-model="form.public_url"
                data-field="public_url"
                class="input mono"
                :class="{ invalid: errors.public_url }"
                placeholder="https://192.168.1.10"
                autocapitalize="none"
                spellcheck="false"
              />
            </FormField>
            <FormField
              label="Giữ dữ liệu thô"
              input-id="c-ret"
              :error="errors.raw_retention_days"
              hint="Từ 30 ngày; dữ liệu gộp 5 phút giữ lâu hơn cho biểu đồ nhiều tháng"
            >
              <div class="affix" :class="{ invalid: errors.raw_retention_days }">
                <input id="c-ret" v-model="form.raw_retention_days" data-field="raw_retention_days" class="tn" inputmode="numeric" /><span>ngày</span>
              </div>
            </FormField>
            <FormField label="Giờ backup hằng ngày" input-id="c-bt" :error="errors.backup_time">
              <input id="c-bt" v-model="form.backup_time" data-field="backup_time" class="input tn" type="time" />
            </FormField>
            <FormField label="Số bản backup giữ lại" input-id="c-bk" :error="errors.backup_keep">
              <input id="c-bk" v-model="form.backup_keep" data-field="backup_keep" class="input tn" inputmode="numeric" />
            </FormField>
          </div>
          <div class="row" style="justify-content: flex-end">
            <button type="submit" class="btn primary" :class="{ busy: busy.save }" :disabled="busy.save"><Icon name="save" />Lưu cài đặt</button>
          </div>
        </form>

        <section class="panel">
          <h2 class="panel-title">Backup</h2>
          <div class="kv">
            <span>Gần nhất</span>
            <span class="tn">{{ s.last_backup ? `${fmtDateTime(s.last_backup.ts)} · ${fmtBytes(s.last_backup.size)}` : 'Chưa có bản nào' }}</span>
            <span>Tệp</span><span class="mono small" style="overflow-wrap: anywhere">{{ s.last_backup?.file ?? '—' }}</span>
            <span>Thư mục</span><span class="mono small" style="overflow-wrap: anywhere">{{ s.backup_dir }}</span>
          </div>
          <div class="small muted">Backup bằng VACUUM INTO, không dừng thu thập. Nên đặt thư mục backup trên USB hoặc ổ khác thẻ nhớ.</div>
          <div class="row wrap gap-8" style="justify-content: flex-end">
            <button type="button" class="btn" :disabled="!s.last_backup" @click="download('/api/admin/backup/latest')"><Icon name="download" />Tải bản mới nhất</button>
            <button type="button" class="btn primary" :class="{ busy: busy.backup }" :disabled="busy.backup" @click="backupNow"><Icon name="save" />Backup ngay</button>
          </div>
        </section>
      </div>

      <section v-if="hmi" class="panel">
        <div class="panel-head">
          <h2 class="panel-title">Màn hình HMI</h2>
          <span class="badge" :class="hmi.status.online ? 'ok' : 'off'"><span class="dot" :class="{ off: !hmi.status.online }" />{{ hmi.status.online ? 'Đang hiển thị' : 'Không hiển thị' }}</span>
        </div>
        <div class="kv">
          <span>Trạng thái</span>
          <span class="tn">{{
            hmi.status.online
              ? `Kết nối từ ${fmtWhen(hmi.status.connected_since)}${hmi.status.width ? ` · ${hmi.status.width} × ${hmi.status.height}` : ''}${hmi.status.kiosk ? ' · Chromium kiosk' : ''}`
              : 'Không có trang HMI nào đang mở. Kiểm tra dịch vụ greenhouse-hmi và màn HDMI.'
          }}</span>
          <span>Địa chỉ trên Datalogger</span><span class="mono small">{{ hmi.url }}</span>
          <span>Mã QR mở</span><span class="mono small">{{ hmi.lan_url }}</span>
        </div>
        <div class="split even" style="align-items: start">
          <div class="col gap-16">
            <fieldset class="col gap-8">
              <legend>Bố cục</legend>
              <label class="choice" :class="{ on: hmi.layout === 'cards' }">
                <input v-model="hmi.layout" type="radio" value="cards" @change="hmiDirty = true" />
                <span><b>HMI thẻ lớn</b><small>Mỗi kênh một thẻ số cỡ lớn, thanh dải đo, xu hướng 1 giờ; nhìn rõ từ xa</small></span>
              </label>
              <label class="choice" :class="{ on: hmi.layout === 'overview' }">
                <input v-model="hmi.layout" type="radio" value="overview" @change="hmiDirty = true" />
                <span><b>Tổng quan</b><small>Giống trang Tổng quan của web app, nhóm theo khu vực</small></span>
              </label>
            </fieldset>
            <label class="check">
              <input v-model="hmi.allow_charts" type="checkbox" @change="hmiDirty = true" />Cho xem biểu đồ lịch sử trên HMI (chỉ khi màn có cảm ứng)
            </label>
            <div class="row wrap gap-8">
              <button type="button" class="btn primary" :class="{ busy: busy.hmi }" :disabled="busy.hmi || !hmiDirty" @click="saveHmi"><Icon name="save" />Lưu</button>
              <button type="button" class="btn" :class="{ busy: busy.reload }" :disabled="busy.reload" @click="reloadHmi"><Icon name="refresh" />Tải lại màn hình HMI</button>
            </div>
          </div>
          <div class="col gap-8" :style="{ opacity: hmi.layout === 'cards' ? 1 : 0.55 }">
            <div class="row">
              <span class="lbl grow">Thẻ trên HMI và thứ tự</span>
              <span class="small muted tn">{{ visibleCount }} thẻ · lưới {{ visibleCount > 6 ? '4 × 2' : '3 × 2' }}</span>
            </div>
            <div
              v-for="(c, i) in hmi.cards"
              :key="c.id"
              class="row gap-8"
              style="padding: 6px 8px 6px 12px; border: 1px solid var(--border); border-radius: 8px; background: #fff"
            >
              <label class="check sm grow" style="min-width: 0">
                <input v-model="c.visible" type="checkbox" @change="hmiDirty = true" />
                <span class="ellipsis">{{ c.label }} <span class="small muted" style="font-weight: 400">{{ c.sub }}</span></span>
              </label>
              <button type="button" class="icon-btn" style="width: 32px; height: 32px" :aria-label="`Đưa ${c.label} lên`" :disabled="i === 0" @click="moveCard(i, -1)">
                <Icon name="arrowUp" :size="16" />
              </button>
              <button
                type="button"
                class="icon-btn"
                style="width: 32px; height: 32px"
                :aria-label="`Đưa ${c.label} xuống`"
                :disabled="i === hmi.cards.length - 1"
                @click="moveCard(i, 1)"
              >
                <Icon name="arrowDown" :size="16" />
              </button>
            </div>
            <span v-if="visibleCount > 8" class="hint err">Tối đa 8 thẻ vừa màn 1280 × 800; thẻ thứ 9 trở đi sẽ rất nhỏ.</span>
          </div>
        </div>
      </section>

      <section class="col gap-12">
        <div class="row wrap gap-12">
          <h2 class="panel-title grow">Nhật ký thay đổi</h2>
          <select v-model="audit.user" class="input sm" style="width: auto" aria-label="Lọc theo người dùng" @change="loadAudit(true)">
            <option value="">Mọi người dùng</option>
            <option v-for="u in audit.users" :key="u" :value="u">{{ u }}</option>
          </select>
          <select v-model="audit.entity" class="input sm" style="width: auto" aria-label="Lọc theo đối tượng" @change="loadAudit(true)">
            <option value="">Mọi đối tượng</option>
            <option v-for="e in audit.entities" :key="e" :value="e">{{ ENTITY_NAMES[e] ?? e }}</option>
          </select>
        </div>
        <div class="tbl-wrap">
          <table class="tbl compact">
            <thead>
              <tr><th>Thời điểm</th><th>Người dùng</th><th>Đối tượng</th><th>Thay đổi</th><th /></tr>
            </thead>
            <tbody>
              <template v-for="r in audit.rows" :key="r.id">
                <tr>
                  <td class="tn nowrap">{{ fmtDateTime(r.ts) }}</td>
                  <td>{{ r.username ?? 'hệ thống' }}</td>
                  <td class="nowrap">{{ ENTITY_NAMES[r.entity] ?? r.entity }} · {{ ACTION_NAMES[r.action] ?? r.action }}</td>
                  <td>{{ r.summary }}</td>
                  <td class="num">
                    <button
                      v-if="r.before || r.after"
                      type="button"
                      class="btn sm ghost"
                      :aria-expanded="audit.open === r.id"
                      @click="audit.open = audit.open === r.id ? null : r.id"
                    >
                      {{ audit.open === r.id ? 'Ẩn' : 'Trước / sau' }}
                    </button>
                  </td>
                </tr>
                <tr v-if="audit.open === r.id">
                  <td colspan="5">
                    <div class="split even" style="gap: 12px">
                      <div class="col gap-4"><span class="small strong">Trước</span><pre class="frames" style="margin: 0; white-space: pre-wrap">{{ pretty(r.before) }}</pre></div>
                      <div class="col gap-4"><span class="small strong">Sau</span><pre class="frames" style="margin: 0; white-space: pre-wrap">{{ pretty(r.after) }}</pre></div>
                    </div>
                  </td>
                </tr>
              </template>
              <tr v-if="!audit.rows.length">
                <td colspan="5" class="muted">Chưa có thay đổi nào{{ audit.user || audit.entity ? ' khớp bộ lọc' : '' }}.</td>
              </tr>
            </tbody>
          </table>
        </div>
        <button v-if="audit.more" type="button" class="btn" style="align-self: center" :class="{ busy: busy.audit }" @click="loadAudit()">Xem thêm</button>
      </section>
    </template>
  </div>
</template>

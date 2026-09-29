// Định dạng số và thời gian kiểu Việt Nam. Thời gian trong API là epoch mili giây UTC,
// hiển thị theo múi giờ của site (mặc định Asia/Ho_Chi_Minh).

let tz = 'Asia/Ho_Chi_Minh';

export function setTimezone(name: string | null | undefined): void {
  if (name && name !== tz) {
    tz = name;
    dtfCache.clear();
  }
}

export const timezone = (): string => tz;

// --- Số --------------------------------------------------------------------------------------

const nfCache = new Map<number, Intl.NumberFormat>();

/** 38200 → "38.200", 3.4 → "3,4"; null hoặc không phải số → "—". */
export function fmtNum(v: number | null | undefined, d = 1): string {
  if (v == null || !Number.isFinite(Number(v))) return '—';
  const key = Math.max(0, Math.min(6, Math.trunc(d)));
  let nf = nfCache.get(key);
  if (!nf) {
    nf = new Intl.NumberFormat('vi-VN', { minimumFractionDigits: key, maximumFractionDigits: key, useGrouping: true });
    nfCache.set(key, nf);
  }
  return nf.format(Number(v));
}

/** Số không cố định chữ số lẻ: 0,1 · 38.200 · 2,5. Rỗng khi không có giá trị. */
export function fmtAuto(v: number | string | null | undefined, maxD = 3): string {
  if (v == null || v === '' || !Number.isFinite(Number(v))) return '';
  const n = Number(v);
  const decimals = Number.isInteger(n) ? 0 : Math.min(maxD, (String(n).split('.')[1] || '').length);
  return fmtNum(n, decimals);
}

/** Đọc số người dùng gõ: "33,8", "33.8", "38.200" (dấu chấm nghìn), "-40". Rỗng → null, sai → NaN. */
export function parseNum(s: string | number | null | undefined): number | null {
  if (s == null) return null;
  if (typeof s === 'number') return Number.isFinite(s) ? s : Number.NaN;
  let t = s.trim().replace(/\s/g, '').replace('−', '-');
  if (t === '') return null;
  if (/^-?\d{1,3}(\.\d{3})+(,\d+)?$/.test(t)) t = t.replace(/\./g, '');
  t = t.replace(',', '.');
  const n = Number(t);
  return Number.isFinite(n) ? n : Number.NaN;
}

export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let v = n;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i++;
  }
  return `${fmtNum(v, v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

// --- Thời gian -------------------------------------------------------------------------------

const dtfCache = new Map<string, Intl.DateTimeFormat>();

function dtf(opts: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = JSON.stringify(opts);
  let f = dtfCache.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat('vi-VN', { timeZone: tz, hourCycle: 'h23', ...opts });
    dtfCache.set(key, f);
  }
  return f;
}

export interface Parts {
  y: string;
  mo: string;
  d: string;
  h: string;
  mi: string;
  s: string;
  wd: string;
}

export function parts(ms: number): Parts {
  const p: Record<string, string> = {};
  const opts: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    weekday: 'long',
  };
  for (const x of dtf(opts).formatToParts(ms)) p[x.type] = x.value;
  return { y: p.year, mo: p.month, d: p.day, h: p.hour === '24' ? '00' : p.hour, mi: p.minute, s: p.second, wd: p.weekday };
}

const cap = (s: string): string => (s ? s[0].toUpperCase() + s.slice(1) : s);

export function fmtTime(ms: number | null | undefined): string {
  if (!ms) return '—';
  const p = parts(ms);
  return `${p.h}:${p.mi}:${p.s}`;
}

export function fmtHM(ms: number | null | undefined): string {
  if (!ms) return '—';
  const p = parts(ms);
  return `${p.h}:${p.mi}`;
}

export function fmtDM(ms: number): string {
  const p = parts(ms);
  return `${p.d}/${p.mo}`;
}

export function fmtDMHM(ms: number | null | undefined): string {
  if (!ms) return '—';
  const p = parts(ms);
  return `${p.d}/${p.mo} ${p.h}:${p.mi}`;
}

export function fmtDate(ms: number): string {
  const p = parts(ms);
  return `${p.d}/${p.mo}/${p.y}`;
}

export function fmtDateTime(ms: number | null | undefined): string {
  if (!ms) return '—';
  const p = parts(ms);
  return `${p.d}/${p.mo}/${p.y} ${p.h}:${p.mi}`;
}

export function fmtWeekday(ms: number): string {
  const p = parts(ms);
  return `${cap(p.wd)}, ${p.d}/${p.mo}/${p.y}`;
}

/** Giờ nếu cùng ngày với hôm nay, không thì kèm ngày. */
export function fmtWhen(ms: number | null | undefined, now = Date.now()): string {
  if (!ms) return '—';
  return fmtDM(ms) === fmtDM(now) ? fmtHM(ms) : fmtDMHM(ms);
}

export function fmtAgo(ms: number | null | undefined, now = Date.now()): string {
  if (!ms) return '';
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 60) return `${s} giây trước`;
  if (s < 3600) return `${Math.round(s / 60)} phút trước`;
  if (s < 86400) return `${Math.round(s / 3600)} giờ trước`;
  return `${Math.round(s / 86400)} ngày trước`;
}

export function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d) return `${d} ngày ${h} giờ`;
  if (h) return `${h} giờ ${m} phút`;
  if (m) return `${m} phút`;
  return `${s} giây`;
}

/** Độ lệch múi giờ hiển thị so với UTC (mili giây) tại thời điểm ms. */
export function tzOffsetMs(ms: number): number {
  const p = parts(ms);
  const asUtc = Date.UTC(+p.y, +p.mo - 1, +p.d, +p.h, +p.mi, +p.s);
  return asUtc - Math.floor(ms / 1000) * 1000;
}

/** Giá trị cho <input type="datetime-local"> theo múi giờ hiển thị, và chiều ngược lại. */
export function toLocalInput(ms: number): string {
  const p = parts(ms);
  return `${p.y}-${p.mo}-${p.d}T${p.h}:${p.mi}`;
}

export function fromLocalInput(s: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(s || '');
  if (!m) return null;
  const guess = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  return guess - tzOffsetMs(guess);
}

// --- Chữ -------------------------------------------------------------------------------------

export const initials = (name: string | null | undefined): string =>
  (name || '?').replace(/[^a-z0-9]/gi, '').slice(0, 2).toUpperCase() || '?';

/** "Node 02 · Nhiệt ẩm, ánh sáng" → "Node 02". */
export const shortName = (name: string | null | undefined): string => String(name || '').split(' · ')[0];

export function rangeText(lo: number | null | undefined, hi: number | null | undefined, unit = ''): string {
  const u = unit ? ` ${unit}` : '';
  if (lo != null && hi != null) return `${fmtAuto(lo)}–${fmtAuto(hi)}${u}`;
  if (hi != null) return `≤ ${fmtAuto(hi)}${u}`;
  if (lo != null) return `≥ ${fmtAuto(lo)}${u}`;
  return '';
}

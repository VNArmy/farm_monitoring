// Trạng thái hiển thị của thẻ số đo (spec mục 7): màu, biểu tượng, nhãn, chân thẻ.
// Bình thường · Vượt ngưỡng · Dữ liệu cũ · Lỗi cảm biến · Mất kết nối, thêm Đang tắt và Đang chờ dữ liệu.
import { fmtAgo, fmtAuto, fmtHM, fmtNum, fmtTime, shortName } from './format';
import type { Metric } from './types';

export const COLORS = {
  spark: '#2F6F58',
  warn: '#B45309',
  grey: '#9A9C95',
  off: '#B4B2A9',
  hmi: '#4A4D47',
};

export interface CardView {
  cls: '' | 'warn' | 'stale' | 'fault' | 'offline' | 'disabled';
  color: string;
  value: string;
  waiting: boolean;
  badge: { cls: string; icon: string | null; text: string; hmiText?: string } | null;
  footL: string;
  footR: string;
  warnFoot: boolean;
  threshold: number | null;
}

export function thresholdText(c: Metric): string {
  const u = c.unit ? ` ${c.unit}` : '';
  const lo = c.alarm_low;
  const hi = c.alarm_high;
  if (lo != null && hi != null) return `Ngưỡng ${fmtAuto(lo)}–${fmtAuto(hi)}${u}`;
  if (hi != null) return `Ngưỡng cao ${fmtAuto(hi)}${u}`;
  if (lo != null) return `Ngưỡng thấp ${fmtAuto(lo)}${u}`;
  return c.note || 'Chưa đặt ngưỡng';
}

/** "Node báo mã lỗi -32768" → "Node 01 báo mã lỗi -32768". */
export function faultText(c: Metric): string {
  const f = c.detail || 'Lỗi cảm biến';
  return f.startsWith('Node ') ? `${shortName(c.device_name)} ${f.slice(5)}` : f;
}

export function cardView(c: Metric, now = Date.now()): CardView {
  const unit = c.unit ? ` ${c.unit}` : '';
  const value = c.value == null ? '—' : fmtNum(c.value, c.decimals);
  const base: CardView = {
    cls: '',
    color: COLORS.spark,
    value,
    waiting: false,
    badge: null,
    footL: '',
    footR: '',
    warnFoot: false,
    threshold: null,
  };
  switch (c.state) {
    case 'alarm': {
      const high = c.alarm === 'high';
      const th = high ? c.alarm_high : c.alarm_low;
      return {
        ...base,
        cls: 'warn',
        color: COLORS.warn,
        threshold: th,
        badge: { cls: 'warn', icon: 'warn', text: 'Vượt ngưỡng', hmiText: `Vượt ngưỡng ${high ? 'cao' : 'thấp'}` },
        footL: `${high ? 'Trên ngưỡng' : 'Dưới ngưỡng'} ${fmtAuto(th)}${unit}`,
        footR: fmtTime(c.ts),
        warnFoot: true,
      };
    }
    case 'stale':
      return {
        ...base,
        cls: 'stale',
        color: COLORS.grey,
        badge: { cls: 'info', icon: 'clock', text: 'Dữ liệu cũ' },
        footL: `Lần cuối ${fmtTime(c.ts)}`,
        footR: fmtAgo(c.ts, now),
      };
    case 'fault':
      return {
        ...base,
        cls: 'fault',
        color: COLORS.grey,
        value: '—',
        badge: { cls: 'danger', icon: 'xCircle', text: 'Lỗi cảm biến' },
        footL: faultText(c),
        footR: c.fault_since ? `từ ${fmtHM(c.fault_since)}` : '',
      };
    case 'out_of_range':
      return {
        ...base,
        cls: 'fault',
        color: COLORS.grey,
        badge: { cls: 'danger', icon: 'warn', text: 'Ngoài phạm vi' },
        footL: c.detail || 'Giá trị ngoài phạm vi hợp lệ của mẫu',
        footR: fmtTime(c.ts),
      };
    case 'offline':
      return {
        ...base,
        cls: 'offline',
        color: COLORS.off,
        value: '—',
        badge: { cls: 'off', icon: 'plugOff', text: 'Mất kết nối' },
        footL: `${shortName(c.device_name)} không phản hồi`,
        footR: c.offline_since ? `từ ${fmtHM(c.offline_since)}` : '',
      };
    case 'disabled':
      return {
        ...base,
        cls: 'disabled',
        color: COLORS.off,
        value: '—',
        badge: { cls: 'off', icon: null, text: 'Đang tắt' },
        footL: 'Thiết bị hoặc kết nối đang tắt',
      };
    case 'nodata':
      // Pi vừa khởi động hoặc thiết bị mới: không hiện ô trống hay số 0 (spec mục 7).
      return {
        ...base,
        cls: 'offline',
        color: COLORS.off,
        value: '',
        waiting: true,
        badge: null,
        footL: 'Đang chờ lần đọc đầu tiên',
      };
    default:
      return {
        ...base,
        badge: c.estimate ? { cls: 'neutral', icon: null, text: 'Ước tính' } : null,
        footL: thresholdText(c),
        footR: c.ts ? fmtTime(c.ts) : '',
      };
  }
}

/** Sparkline trong hộp W×H; ngắt nét ở khoảng trống dài hơn gapMs. */
export function sparkPath(
  points: [number, number][] | undefined,
  from: number,
  to: number,
  lo: number,
  hi: number,
  W: number,
  H: number,
  gapMs: number,
): string {
  if (!points?.length) return '';
  let a = lo;
  let b = hi;
  if (!(b - a > 1e-9)) {
    a -= 1;
    b += 1;
  }
  const pad = 4;
  const span = Math.max(1, to - from);
  let d = '';
  let prev: number | null = null;
  for (const [t, v] of points) {
    if (t < from || v == null) continue;
    const x = ((t - from) / span) * W;
    const y = H - pad - ((v - a) / (b - a)) * (H - 2 * pad);
    d += (d === '' || (prev != null && t - prev > gapMs) ? 'M' : 'L') + x.toFixed(1) + ' ' + y.toFixed(1);
    prev = t;
  }
  return d;
}

export function sparkRange(min: number | null | undefined, max: number | null | undefined, threshold: number | null): [number, number] {
  if (min == null || max == null) return [0, 1];
  let lo = min;
  let hi = max;
  if (threshold != null) {
    lo = Math.min(lo, threshold);
    hi = Math.max(hi, threshold);
  }
  const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.02 || 1;
  return [lo - pad, hi + pad];
}

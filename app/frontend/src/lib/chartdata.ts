// Chuẩn bị dữ liệu /api/readings cho uPlot: gộp trục thời gian của mọi kênh, đánh dấu khoảng mất dữ liệu,
// tính thang trục Y theo đơn vị. Tách khỏi component để kiểm thử được.
import type { History, Series } from './types';

/** Giá trị trong cột uPlot: undefined là "kênh này không có điểm ở mốc đó" (nối qua), null là đứt đoạn. */
export type Cell = number | null | undefined;

export interface Aligned {
  /** Mốc thời gian, giây (uPlot dùng giây cho trục thời gian). */
  xs: number[];
  avg: Cell[][];
  min: Cell[][];
  max: Cell[][];
}

export function align(d: History): Aligned {
  const set = new Set<number>();
  for (const s of d.series) {
    for (const p of s.points) set.add(p[0]);
    for (const g of s.gaps) set.add(g[0]);
  }
  const ms = [...set].sort((a, b) => a - b);
  const pos = new Map<number, number>();
  ms.forEach((t, i) => pos.set(t, i));
  const n = ms.length;
  const out: Aligned = { xs: ms.map((t) => t / 1000), avg: [], min: [], max: [] };
  for (const s of d.series) {
    const avg: Cell[] = new Array<Cell>(n).fill(undefined);
    const mn: Cell[] = new Array<Cell>(n).fill(undefined);
    const mx: Cell[] = new Array<Cell>(n).fill(undefined);
    for (const p of s.points) {
      const i = pos.get(p[0]) as number;
      avg[i] = p[1];
      mn[i] = p[2];
      mx[i] = p[3];
    }
    // Đầu mỗi khoảng mất dữ liệu đặt null để đường và dải đứt đoạn, không nối thẳng (spec mục 7).
    for (const g of s.gaps) {
      const i = pos.get(g[0]) as number;
      if (avg[i] === undefined) {
        avg[i] = null;
        mn[i] = null;
        mx[i] = null;
      }
    }
    out.avg.push(avg);
    out.min.push(mn);
    out.max.push(mx);
  }
  return out;
}

/** Tối đa 2 đơn vị, theo thứ tự kênh xuất hiện. */
export function unitsOf(series: { unit: string }[]): string[] {
  return [...new Set(series.map((s) => s.unit))].slice(0, 2);
}

/** Khoảng trục Y cho một đơn vị: đủ chứa dải thấp nhất–cao nhất và ngưỡng gần dữ liệu; số không âm thì không xuống dưới 0. */
export function yRange(series: Series[], agg: boolean): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const s of series) {
    for (const p of s.points) {
      const a = agg ? p[2] : p[1];
      const b = agg ? p[3] : p[1];
      if (a < lo) lo = a;
      if (b > hi) hi = b;
    }
  }
  if (!Number.isFinite(lo)) return [0, 1];
  const nonNeg = lo >= 0;
  const span = hi - lo;
  for (const s of series) {
    for (const th of [s.alarm_low, s.alarm_high]) {
      if (th != null && th > lo - span - 1e-9 && th < hi + span + 1e-9) {
        lo = Math.min(lo, th);
        hi = Math.max(hi, th);
      }
    }
  }
  if (hi - lo < 1e-9) {
    const p = Math.abs(hi) * 0.1 || 1;
    lo -= p;
    hi += p;
  }
  const pad = (hi - lo) * 0.06;
  lo -= pad;
  hi += pad;
  if (nonNeg) lo = Math.max(0, lo);
  return [lo, hi];
}

/** Số chữ số lẻ cho nhãn trục theo bước chia: 0,5 → 1; 0,25 → 2; 20 → 0. */
export function decimalsOfStep(step: number): number {
  if (!(step > 0)) return 0;
  const s = String(Number(step.toPrecision(6)));
  const e = s.indexOf('e-');
  if (e >= 0) return Math.min(4, Number(s.slice(e + 2)));
  return Math.min(4, (s.split('.')[1] ?? '').length);
}

/** Chỉ số điểm gần thời điểm t nhất (points sắp theo thời gian); -1 khi rỗng. */
export function nearest(points: [number, ...number[]][], t: number): number {
  let lo = 0;
  let hi = points.length - 1;
  if (hi < 0) return -1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (points[mid][0] < t) lo = mid;
    else hi = mid;
  }
  return Math.abs(points[lo][0] - t) <= Math.abs(points[hi][0] - t) ? lo : hi;
}

/** Khoảng mất dữ liệu không trùng lặp: một node mất kết nối làm trống mọi kênh của nó, chỉ tính một lần. */
export function uniqueGaps(series: Series[]): { device: string; from: number; to: number }[] {
  const seen = new Set<string>();
  const out: { device: string; from: number; to: number }[] = [];
  for (const s of series) {
    for (const [a, b] of s.gaps) {
      const k = `${s.device_name}|${a}|${b}`;
      if (seen.has(k)) continue;
      seen.add(k);
      out.push({ device: s.device_name, from: a, to: b });
    }
  }
  return out.sort((x, y) => y.to - y.from - (x.to - x.from));
}

<script setup lang="ts">
// Biểu đồ lịch sử bằng uPlot (spec mục 7): tối đa 2 trục Y theo đơn vị, đường trung bình kèm dải thấp nhất–cao nhất
// khi dữ liệu đã gộp, đứt đoạn ở khoảng mất dữ liệu (tô nền xám), vạch ngưỡng nét đứt, tooltip theo con trỏ.
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { align, decimalsOfStep, nearest, unitsOf, yRange } from '../lib/chartdata';
import { fmtDM, fmtDMHM, fmtHM, fmtNum, fmtTime, parts, timezone } from '../lib/format';
import { alpha, darkOf, lightOf } from '../lib/palette';
import type { History } from '../lib/types';

const props = withDefaults(defineProps<{ data: History; colors: Record<number, string>; height?: number }>(), {
  height: 460,
});

const box = ref<HTMLElement>();
let plot: uPlot | null = null;
let ro: ResizeObserver | null = null;

interface TipRow {
  color: string;
  label: string;
  value: string;
  sub: string;
}
const tip = reactive<{ show: boolean; left: number; time: string; rows: TipRow[] }>({ show: false, left: 0, time: '', rows: [] });

const FONT = '12px "Be Vietnam Pro", system-ui, sans-serif';
const AXIS = '#6B6E67';
const GRID = '#EFEDE7';
const GAP_FILL = '#ECEAE4';

function heightFor(w: number): number {
  return w < 560 ? Math.min(props.height, 300) : props.height;
}

function axisSize(_u: uPlot, values: string[] | null): number {
  const w = Math.max(0, ...(values ?? []).map((v) => v.length)) * 7.4 + 18;
  return Math.ceil(Math.max(40, w));
}

function build(): void {
  const el = box.value;
  if (!el) return;
  plot?.destroy();
  plot = null;
  tip.show = false;

  const d = props.data;
  const agg = d.bucket_ms > 0;
  const units = unitsOf(d.series);
  const shown = d.series.filter((s) => units.includes(s.unit));
  const al = align({ ...d, series: shown });
  const colorOf = (id: number): string => props.colors[id] ?? '#52554F';
  const scaleOf = (unit: string): string => `y${units.indexOf(unit)}`;
  const ranges = units.map((u) =>
    yRange(
      shown.filter((s) => s.unit === u),
      agg,
    ),
  );

  const series: uPlot.Series[] = [{}];
  const cols: (number | null | undefined)[][] = [];
  const bands: uPlot.Band[] = [];
  shown.forEach((s, i) => {
    const color = colorOf(s.channel_id);
    series.push({
      label: `${s.label} · ${s.zone}`,
      scale: scaleOf(s.unit),
      stroke: color,
      width: 1.75,
      spanGaps: false,
      points: { show: false },
    });
    cols.push(al.avg[i]);
    if (agg) {
      const hiIdx = series.length;
      series.push({ scale: scaleOf(s.unit), stroke: 'transparent', width: 0, spanGaps: false, points: { show: false } });
      cols.push(al.max[i]);
      series.push({ scale: scaleOf(s.unit), stroke: 'transparent', width: 0, spanGaps: false, points: { show: false } });
      cols.push(al.min[i]);
      bands.push({ series: [hiIdx, hiIdx + 1], fill: alpha(color, 0.13) });
    }
  });

  const span = d.to - d.from;
  const axes: uPlot.Axis[] = [
    {
      stroke: AXIS,
      font: FONT,
      space: 70,
      grid: { stroke: '#F3F2EE', width: 1 },
      ticks: { show: false },
      values: (_u, splits, _ai, _space, incr) =>
        splits.map((sec) => {
          const ms = sec * 1000;
          if (incr >= 86400) return fmtDM(ms);
          if (span > 36 * 3_600_000) {
            const p = parts(ms);
            if (p.h === '00' && p.mi === '00') return fmtDM(ms);
          }
          return fmtHM(ms);
        }),
    },
  ];
  units.forEach((u, i) => {
    const onAxis = shown.filter((s) => s.unit === u);
    axes.push({
      scale: `y${i}`,
      side: i === 0 ? 3 : 1,
      stroke: onAxis.length === 1 ? darkOf(colorOf(onAxis[0].channel_id)) : '#52554F',
      font: FONT,
      size: axisSize,
      grid: { show: i === 0, stroke: GRID, width: 1 },
      ticks: { show: false },
      values: (_u, splits, _ai, _space, incr) => splits.map((v) => fmtNum(v, decimalsOfStep(incr))),
    });
  });

  const scales: uPlot.Scales = { x: { time: true, range: () => [d.from / 1000, d.to / 1000] } };
  units.forEach((_u, i) => {
    scales[`y${i}`] = { range: () => ranges[i] };
  });

  const w = Math.max(280, Math.floor(el.clientWidth));
  const opts: uPlot.Options = {
    width: w,
    height: heightFor(w),
    tzDate: (ts) => uPlot.tzDate(new Date(ts * 1000), timezone()),
    series,
    bands,
    axes,
    scales,
    legend: { show: false },
    padding: [12, units.length > 1 ? 4 : 16, 4, 4],
    cursor: {
      drag: { x: false, y: false, setScale: false },
      points: { show: true, size: 9, width: 2, fill: '#FFFFFF' },
      y: false,
    },
    hooks: {
      drawClear: [
        (u) => {
          // Khoảng không có dữ liệu: nền xám nhạt trên cả chiều cao vùng vẽ.
          const ctx = u.ctx;
          ctx.save();
          ctx.fillStyle = GAP_FILL;
          const { left, top, width, height } = u.bbox;
          for (const s of shown) {
            for (const [a, b] of s.gaps) {
              const x1 = Math.max(left, u.valToPos(a / 1000, 'x', true));
              const x2 = Math.min(left + width, u.valToPos(b / 1000, 'x', true));
              if (x2 - x1 > 0.5) ctx.fillRect(x1, top, x2 - x1, height);
            }
          }
          ctx.restore();
        },
      ],
      draw: [
        (u) => {
          // Ngưỡng cảnh báo: nét đứt màu đậm của kênh.
          const ctx = u.ctx;
          const pr = uPlot.pxRatio;
          const { left, top, width, height } = u.bbox;
          ctx.save();
          ctx.lineWidth = 1.25 * pr;
          ctx.setLineDash([5 * pr, 4 * pr]);
          for (const s of shown) {
            const key = scaleOf(s.unit);
            const sc = u.scales[key];
            for (const th of [s.alarm_low, s.alarm_high]) {
              if (th == null || sc.min == null || sc.max == null || th < sc.min || th > sc.max) continue;
              const y = Math.round(u.valToPos(th, key, true)) + 0.5;
              if (y < top || y > top + height) continue;
              ctx.strokeStyle = darkOf(colorOf(s.channel_id));
              ctx.beginPath();
              ctx.moveTo(left, y);
              ctx.lineTo(left + width, y);
              ctx.stroke();
            }
          }
          ctx.restore();
        },
      ],
      setCursor: [(u) => showTip(u)],
    },
  };

  function showTip(u: uPlot): void {
    const idx = u.cursor.idx;
    const cl = u.cursor.left ?? -1;
    if (idx == null || cl < 0) {
      tip.show = false;
      return;
    }
    const tt = al.xs[idx] * 1000;
    const rows: TipRow[] = [];
    for (const s of shown) {
      const j = nearest(s.points, tt);
      const p = j >= 0 ? s.points[j] : null;
      const ok = p != null && Math.abs(p[0] - tt) <= s.interval_ms;
      const dd = s.decimals ?? 1;
      rows.push({
        color: lightOf(colorOf(s.channel_id)),
        label: s.label,
        value: ok ? `${fmtNum(p[1], dd)} ${s.unit}` : 'không có dữ liệu',
        sub: ok && agg ? `Thấp nhất ${fmtNum(p[2], dd)} · cao nhất ${fmtNum(p[3], dd)}` : '',
      });
    }
    const host = box.value;
    if (!host) return;
    const ob = u.over.getBoundingClientRect();
    const hb = host.getBoundingClientRect();
    const x = ob.left - hb.left + cl;
    tip.left = Math.max(0, x + 16 + 240 > hb.width ? x - 16 - 240 : x + 16);
    tip.time = agg ? fmtDMHM(tt) : `${fmtDM(tt)} ${fmtTime(tt)}`;
    tip.rows = rows;
    tip.show = true;
  }

  plot = new uPlot(opts, [al.xs, ...cols] as uPlot.AlignedData, el);
}

function resize(): void {
  const el = box.value;
  if (!el || !plot) return;
  const w = Math.max(280, Math.floor(el.clientWidth));
  const h = heightFor(w);
  if (w !== plot.width || h !== plot.height) plot.setSize({ width: w, height: h });
}

onMounted(() => {
  build();
  ro = new ResizeObserver(() => resize());
  if (box.value) ro.observe(box.value);
});

watch(
  () => [props.data, props.colors],
  () => build(),
);

onBeforeUnmount(() => {
  ro?.disconnect();
  plot?.destroy();
  plot = null;
});
</script>

<template>
  <div class="chart-box" role="img" :aria-label="data.series.map((s) => `${s.label} ${s.zone}`).join(', ')">
    <div ref="box" />
    <div v-show="tip.show" class="chart-tip" :style="{ left: `${tip.left}px` }">
      <div class="tn strong">{{ tip.time }}</div>
      <div v-for="(r, i) in tip.rows" :key="i" class="col gap-4">
        <div class="row gap-6">
          <span class="sw" :style="{ background: r.color }" /><span class="grow">{{ r.label }}</span
          ><span class="tn strong">{{ r.value }}</span>
        </div>
        <div v-if="r.sub" class="sub tn">{{ r.sub }}</div>
      </div>
    </div>
  </div>
</template>

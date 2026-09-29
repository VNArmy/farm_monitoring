<script setup lang="ts">
// Thanh dải đo (spec mục 7): vẽ theo thang hiển thị của kênh, vùng ngoài ngưỡng tô nhạt, vạch đậm là giá trị.
// Giá trị ngoài thang: vạch dừng ở mép kèm mũi tên, con số trên thẻ vẫn hiện đúng.
import { computed } from 'vue';
import { fmtAuto } from '../lib/format';
import type { Spark } from '../lib/types';

interface Scale {
  display_min: number | null;
  display_max: number | null;
  alarm_low: number | null;
  alarm_high: number | null;
  alarm?: 'high' | 'low' | null;
  state?: string;
}

const props = withDefaults(defineProps<{ m: Scale; value: number | null; small?: boolean; spark?: Spark | null }>(), {
  small: false,
  spark: null,
});

const bar = computed(() => {
  const m = props.m;
  let lo = m.display_min;
  let hi = m.display_max;
  if (lo == null || hi == null || !(hi > lo)) {
    // Kênh chưa có thang: dựng tạm từ dữ liệu 1 giờ để thanh vẫn có nghĩa.
    const a = props.spark?.min ?? props.value ?? 0;
    const b = props.spark?.max ?? props.value ?? 1;
    const pad = Math.abs(b - a) * 0.5 || Math.abs(b) * 0.2 || 1;
    lo = lo ?? Math.floor(a - pad);
    hi = hi ?? Math.ceil(b + pad);
    if (!(hi > lo)) hi = lo + 1;
  }
  const L = lo;
  const H = hi;
  const pct = (v: number): number => Math.max(0, Math.min(100, ((v - L) / (H - L)) * 100));
  const warn = m.state === 'alarm' || (m.state == null && props.value != null && isOutside(props.value));
  const v = props.value;
  const out = v == null ? null : v < L ? 'l' : v > H ? 'r' : null;
  const nearL = m.alarm_low != null && pct(m.alarm_low) <= 12;
  const nearR = m.alarm_high != null && pct(m.alarm_high) >= 88;
  return {
    lo: L,
    hi: H,
    pct,
    warn,
    out,
    mark: v == null ? null : pct(v),
    showLo: !nearL,
    showHi: !nearR,
  };
});

function isOutside(v: number): boolean {
  const m = props.m;
  return (m.alarm_high != null && v > m.alarm_high) || (m.alarm_low != null && v < m.alarm_low);
}
</script>

<template>
  <div :class="small ? '' : 'col gap-6'">
    <div class="rbar" :class="{ sm: small }" aria-hidden="true">
      <div class="rbar-track">
        <div v-if="m.alarm_low != null" class="rbar-zone" :style="{ left: 0, width: `${bar.pct(m.alarm_low).toFixed(2)}%` }" />
        <div v-if="m.alarm_high != null" class="rbar-zone" :style="{ left: `${bar.pct(m.alarm_high).toFixed(2)}%`, right: 0 }" />
      </div>
      <div v-if="bar.mark != null" class="rbar-mark" :class="{ warn: bar.warn }" :style="{ left: `${bar.mark.toFixed(2)}%` }" />
      <span v-if="bar.out" class="rbar-arrow" :class="[bar.out, { warn: bar.warn }]" />
    </div>
    <div v-if="!small" class="rbar-ticks">
      <span v-if="bar.showLo" class="l">{{ fmtAuto(bar.lo) }}</span>
      <span v-if="m.alarm_low == null && m.alarm_high == null" style="left: 50%">Chưa đặt ngưỡng</span>
      <template v-else>
        <span
          v-if="m.alarm_low != null"
          :class="{ warn: bar.warn && m.alarm === 'low' }"
          :style="{ left: `${bar.pct(m.alarm_low).toFixed(2)}%` }"
          >{{ fmtAuto(m.alarm_low) }}</span
        >
        <span
          v-if="m.alarm_high != null"
          :class="{ warn: bar.warn && m.alarm === 'high' }"
          :style="{ left: `${bar.pct(m.alarm_high).toFixed(2)}%` }"
          >{{ fmtAuto(m.alarm_high) }}</span
        >
      </template>
      <span v-if="bar.showHi" class="r">{{ fmtAuto(bar.hi) }}</span>
    </div>
  </div>
</template>

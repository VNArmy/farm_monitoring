<script setup lang="ts">
// Đường xu hướng 1 giờ trên thẻ; vạch đứt là ngưỡng đang bị vượt.
import { computed } from 'vue';
import { sparkPath, sparkRange } from '../lib/cards';
import type { Spark } from '../lib/types';

const props = withDefaults(
  defineProps<{
    spark: Spark | null;
    now: number;
    color: string;
    threshold?: number | null;
    pollS?: number;
    cls?: string;
    W?: number;
    H?: number;
    width?: number;
  }>(),
  { threshold: null, pollS: 10, cls: 'mc-spark', W: 200, H: 48, width: 2 },
);

const geo = computed(() => {
  const from = props.now - 3_600_000;
  const [lo, hi] = sparkRange(props.spark?.min, props.spark?.max, props.threshold);
  // Điểm xu hướng là trung bình mỗi phút: khoảng trống trên 3 phút (hoặc 3 chu kỳ đọc) là mất dữ liệu.
  const gap = Math.max(180_000, props.pollS * 3000 + 30_000);
  const d = sparkPath(props.spark?.points, from, props.now, lo, hi, props.W, props.H, gap);
  const thY = props.threshold == null ? null : props.H - 4 - ((props.threshold - lo) / (hi - lo)) * (props.H - 8);
  return { d, thY };
});
</script>

<template>
  <svg :class="cls" :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none" aria-hidden="true">
    <line
      v-if="geo.thY != null"
      x1="0"
      :y1="geo.thY"
      :x2="W"
      :y2="geo.thY"
      style="stroke: #b45309; stroke-width: 1; stroke-dasharray: 4 4; vector-effect: non-scaling-stroke"
    />
    <path
      :d="geo.d"
      :style="{
        fill: 'none',
        stroke: color,
        strokeWidth: width,
        strokeLinejoin: 'round',
        strokeLinecap: 'round',
        vectorEffect: 'non-scaling-stroke',
      }"
    />
  </svg>
</template>

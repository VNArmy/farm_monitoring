<script setup lang="ts">
// Thẻ lớn trên màn hình HMI: số cỡ lớn theo chiều cao màn, thanh dải đo, xu hướng 1 giờ, thấp và cao trong 1 giờ.
import { computed } from 'vue';
import { RouterLink } from 'vue-router';
import { COLORS, cardView } from '../lib/cards';
import { fmtNum, fmtTime } from '../lib/format';
import type { Metric, Spark } from '../lib/types';
import Icon from './Icon.vue';
import RangeBar from './RangeBar.vue';
import Sparkline from './Sparkline.vue';

const props = defineProps<{ m: Metric; spark: Spark | null; now: number; chartLink: boolean }>();

const v = computed(() => cardView(props.m, props.now));
const live = computed(() => props.m.state === 'ok' || props.m.state === 'alarm');
const barValue = computed(() => (['ok', 'alarm', 'stale', 'out_of_range'].includes(props.m.state) ? props.m.value : null));
const sparkColor = computed(() => (v.value.cls === 'warn' ? COLORS.warn : v.value.cls ? v.value.color : COLORS.hmi));
const minMax = computed(() => {
  const s = props.spark;
  const d = props.m.decimals ?? 1;
  return s && s.min != null && s.max != null ? `1 giờ · thấp ${fmtNum(s.min, d)} · cao ${fmtNum(s.max, d)}` : '1 giờ · chưa có dữ liệu';
});
const link = computed(() => (props.chartLink && typeof props.m.id === 'number' ? `/hmi/bieu-do?kenh=${props.m.id}` : null));
</script>

<template>
  <component :is="link ? RouterLink : 'div'" :to="link ?? undefined" class="hcard" :class="v.cls">
    <div class="hc-in">
      <div class="hc-head">
        <span class="hc-title">{{ m.label }}</span>
        <span class="hc-area">{{ m.zone }}</span>
        <span v-if="v.badge" class="badge" :class="v.badge.cls"
          ><Icon v-if="v.badge.icon" :name="v.badge.icon" :size="16" />{{ v.badge.hmiText ?? v.badge.text }}</span
        >
      </div>
      <div class="hc-value">
        <span v-if="v.waiting" class="hc-wait">Đang chờ dữ liệu</span>
        <template v-else>
          <span class="hc-num">{{ v.value }}</span><span class="hc-unit">{{ m.unit }}</span>
        </template>
      </div>
      <RangeBar :m="m" :value="barValue" :spark="spark" />
      <div class="hc-bottom">
        <Sparkline
          :spark="spark"
          :now="now"
          :color="sparkColor"
          :threshold="v.cls === 'warn' ? v.threshold : null"
          :poll-s="m.poll_s"
          cls="hc-spark"
          :H="40"
          :width="2.25"
        />
        <div class="hc-foot">
          <span class="tn">{{ live ? minMax : v.footL }}</span>
          <span class="tn">{{ live ? fmtTime(m.ts) : v.footR }}</span>
        </div>
      </div>
    </div>
  </component>
</template>

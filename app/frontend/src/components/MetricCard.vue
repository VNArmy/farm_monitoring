<script setup lang="ts">
// Thẻ số đo trên trang Tổng quan: tên kênh, giá trị, đơn vị, thời điểm cập nhật, xu hướng 1 giờ.
import { computed } from 'vue';
import { RouterLink } from 'vue-router';
import { cardView } from '../lib/cards';
import { fmtHM } from '../lib/format';
import { channelIcon } from '../lib/icons';
import type { Metric, Spark } from '../lib/types';
import Icon from './Icon.vue';
import Sparkline from './Sparkline.vue';

const props = defineProps<{ m: Metric; spark: Spark | null; now: number; chartBase: string | null }>();

const v = computed(() => cardView(props.m, props.now));
const link = computed(() =>
  props.chartBase && typeof props.m.id === 'number' ? `${props.chartBase}?kenh=${props.m.id}&khoang=24h` : null,
);
const aria = computed(() => `${props.m.label} ${props.m.zone}: ${v.value.waiting ? 'đang chờ dữ liệu' : `${v.value.value} ${props.m.unit}`}`);
</script>

<template>
  <component :is="link ? RouterLink : 'div'" :to="link ?? undefined" class="mcard" :class="v.cls" :aria-label="aria">
    <div class="mc-in">
      <div class="mc-head">
        <Icon :name="channelIcon(m.key, m.unit)" :size="16" class="mc-icon" />
        <span class="mc-title">{{ m.label }}</span>
        <span v-if="v.badge" class="badge" :class="v.badge.cls"><Icon v-if="v.badge.icon" :name="v.badge.icon" :size="14" />{{ v.badge.text }}</span>
        <span class="mc-time tn">{{ m.ts ? fmtHM(m.ts) : '' }}</span>
      </div>
      <div class="mc-value">
        <span v-if="v.waiting" class="mc-wait">Đang chờ dữ liệu</span>
        <template v-else>
          <span class="mc-num">{{ v.value }}</span><span class="mc-unit">{{ m.unit }}</span>
        </template>
      </div>
      <Sparkline :spark="spark" :now="now" :color="v.color" :threshold="v.cls === 'warn' ? v.threshold : null" :poll-s="m.poll_s" />
      <div class="mc-foot">
        <span :class="{ 'mc-foot-warn': v.warnFoot }">{{ v.footL }}</span><span class="tn">{{ v.footR }}</span>
      </div>
    </div>
  </component>
</template>

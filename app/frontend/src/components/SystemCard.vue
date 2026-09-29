<script setup lang="ts">
// Thẻ Hệ thống trên HMI: đồng hồ, số cảnh báo, trạng thái collector và từng node.
import { computed } from 'vue';
import { fmtHM, fmtNum, fmtTime, fmtWeekday, shortName } from '../lib/format';
import type { Snapshot } from '../lib/types';
import Icon from './Icon.vue';

const props = defineProps<{ snap: Snapshot; now: number }>();

const col = computed(() => props.snap.collector);
const alert = computed(() => {
  const c = col.value;
  const alarms = props.snap.alarms;
  if (!c.online) return { cls: 'danger', icon: 'xCircle', text: 'Collector đang dừng: không có dữ liệu mới' };
  if (c.waiting) return { cls: 'ok', icon: 'clock', text: 'Đang chờ dữ liệu từ collector' };
  if (alarms.length) {
    const a = alarms[0];
    const more = alarms.length > 1 ? ` và ${alarms.length - 1} kênh khác` : ` ${fmtNum(a.value, a.decimals)} ${a.unit}`;
    return { cls: 'warn', icon: 'warn', text: `${alarms.length} cảnh báo · ${a.label} ${a.zone}${more}` };
  }
  return { cls: 'ok', icon: 'check', text: 'Không có cảnh báo' };
});

function deviceRight(d: Snapshot['devices'][number]): string {
  if (d.state === 'online') return d.rtt_ms != null ? `${Math.round(d.rtt_ms)} ms` : '';
  if (d.state === 'offline') return d.since ? `mất kết nối từ ${fmtHM(d.since)}` : 'mất kết nối';
  if (d.state === 'stale') return d.last_ok_at ? `lần cuối ${fmtTime(d.last_ok_at)}` : 'dữ liệu cũ';
  if (d.state === 'disabled') return 'đang tắt';
  return 'chưa có dữ liệu';
}

const dotCls = (s: string): string => (s === 'online' ? '' : s === 'offline' ? 'err' : s === 'stale' ? 'info' : 'off');
</script>

<template>
  <section class="hcard" aria-label="Hệ thống">
    <div class="hc-in">
      <div class="hc-head">
        <span class="hc-title">Hệ thống</span>
        <span class="hc-area">{{ snap.site_name }}</span>
        <span class="row gap-6 ml-auto fs-13 nowrap" style="color: var(--text-2)">
          <span class="dot" :class="col.online ? '' : 'err'" />{{ col.online ? 'Trực tiếp' : 'Collector dừng' }}
        </span>
      </div>
      <div class="col gap-4">
        <span class="hc-sys-clock">{{ fmtTime(now) }}</span>
        <span style="font-size: 16px; line-height: 22px; color: var(--text-2)">{{ fmtWeekday(now) }}</span>
      </div>
      <div class="hc-alert" :class="alert.cls"><Icon :name="alert.icon" />{{ alert.text }}</div>
      <div class="hc-sys-list">
        <div>
          <span class="dot lg" :class="col.online ? '' : 'err'" />
          <span class="grow">{{ col.online ? 'Collector đang chạy' : 'Collector đang dừng' }}</span>
          <span class="tn small" style="color: #5f625b">{{ col.last_commit_at ? `ghi ${fmtTime(col.last_commit_at)}` : '' }}</span>
        </div>
        <div v-for="d in snap.devices" :key="d.id">
          <span class="dot lg" :class="dotCls(d.state)" />
          <span class="grow ellipsis">{{ shortName(d.name) }} · {{ d.zone }}</span>
          <span class="tn small" style="color: #5f625b">{{ deviceRight(d) }}</span>
        </div>
        <div v-if="col.clock_warning">
          <Icon name="clock" /><span class="grow small">{{ col.clock_warning }}</span>
        </div>
      </div>
    </div>
  </section>
</template>

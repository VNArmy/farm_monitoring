<script setup lang="ts">
// Khung Modbus dạng hex; các byte của từng kênh tô màu để đối chiếu với giá trị đã giải mã.
import { computed } from 'vue';

const props = withDefaults(defineProps<{ hex: string; highlights?: { key: string; start: number; len: number }[]; colors?: Record<string, string> }>(), {
  highlights: () => [],
  colors: () => ({}),
});

const parts = computed(() => {
  const bytes = props.hex.split(/\s+/).filter(Boolean);
  const out: { text: string; key: string | null }[] = [];
  let i = 0;
  const hs = [...props.highlights].sort((a, b) => a.start - b.start);
  for (const h of hs) {
    if (h.start > i) out.push({ text: bytes.slice(i, h.start).join(' '), key: null });
    out.push({ text: bytes.slice(Math.max(i, h.start), h.start + h.len).join(' '), key: h.key });
    i = Math.max(i, h.start + h.len);
  }
  if (i < bytes.length) out.push({ text: bytes.slice(i).join(' '), key: null });
  return out.filter((p) => p.text);
});
</script>

<template>
  <span class="mono hexline"
    ><template v-for="(p, i) in parts" :key="i"
      >{{ i ? ' ' : '' }}<mark v-if="p.key" :style="{ background: colors[p.key] ?? '#FDEBD3' }" :title="p.key">{{ p.text }}</mark
      ><template v-else>{{ p.text }}</template></template
    ></span
  >
</template>

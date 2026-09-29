<script setup lang="ts">
// Mã QR sinh ngay trong trình duyệt (spec mục 8.7): không gọi dịch vụ ngoài, chạy được khi mất Internet.
import qrcode from 'qrcode-generator';
import { computed } from 'vue';

const props = defineProps<{ text: string }>();

const svg = computed(() => {
  if (!props.text) return '';
  const qr = qrcode(0, 'M');
  qr.addData(props.text);
  qr.make();
  const n = qr.getModuleCount();
  let d = '';
  for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) d += `M${c + 2} ${r + 2}h1v1h-1z`;
  return `<svg viewBox="0 0 ${n + 4} ${n + 4}" shape-rendering="crispEdges" role="img" aria-label="Mã QR: ${props.text.replace(/[<>&"]/g, '')}"><rect width="100%" height="100%" fill="#fff"/><path d="${d}" fill="#1C1E1B"/></svg>`;
});
</script>

<template>
  <div class="qr" v-html="svg" />
</template>

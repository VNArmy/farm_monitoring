<script setup lang="ts">
// Hộp thoại: Esc hoặc bấm nền để đóng, focus vào ô đầu tiên khi mở, trả focus khi đóng.
import { onBeforeUnmount, onMounted, ref } from 'vue';
import Icon from './Icon.vue';

withDefaults(defineProps<{ title: string; size?: '' | 'sm' | 'lg' }>(), { size: '' });
const emit = defineEmits<{ close: [] }>();

const box = ref<HTMLElement>();
const opener = document.activeElement as HTMLElement | null;

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') emit('close');
}

onMounted(() => {
  document.addEventListener('keydown', onKey);
  const first = box.value?.querySelector<HTMLElement>('input:not([type=hidden]):not([disabled]), select, textarea');
  (first ?? box.value)?.focus({ preventScroll: true });
});

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey);
  opener?.focus?.({ preventScroll: true });
});
</script>

<template>
  <Teleport to="body">
    <div class="modal-back" @mousedown.self="emit('close')">
      <div ref="box" class="modal" :class="size" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1">
        <div class="modal-head">
          <h2>{{ title }}</h2>
          <button type="button" class="icon-btn" aria-label="Đóng" @click="emit('close')"><Icon name="x" /></button>
        </div>
        <slot />
        <div v-if="$slots.foot" class="modal-foot"><slot name="foot" /></div>
      </div>
    </div>
  </Teleport>
</template>

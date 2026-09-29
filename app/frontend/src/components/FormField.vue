<script setup lang="ts">
// Nhãn, ô nhập (slot), gợi ý hoặc lỗi của đúng ô đó.
withDefaults(defineProps<{ label?: string; inputId?: string; error?: string; hint?: string; span2?: boolean; sm?: boolean }>(), {
  label: '',
  inputId: undefined,
  error: '',
  hint: '',
  span2: false,
  sm: false,
});
</script>

<template>
  <div class="field" :class="{ 'span-2': span2, sm }">
    <label v-if="label" :for="inputId">{{ label }}</label>
    <slot />
    <span v-if="error" class="hint err" role="alert">{{ error }}</span>
    <span v-else-if="hint" class="hint">{{ hint }}</span>
  </div>
</template>

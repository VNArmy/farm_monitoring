<script setup lang="ts">
// Thông báo nhanh và hộp xác nhận dùng chung cho mọi trang (lib/ui.ts).
import { confirmState, toasts } from '../lib/ui';
import Modal from './Modal.vue';
</script>

<template>
  <div class="toasts" aria-live="polite">
    <div v-for="t in toasts" :key="t.id" class="toast" :class="t.kind" :role="t.kind === 'err' ? 'alert' : 'status'">{{ t.message }}</div>
  </div>
  <Modal v-if="confirmState.current" :title="confirmState.current.title" size="sm" @close="confirmState.current.resolve(false)">
    <p style="margin: 0; white-space: pre-line" class="text-3">{{ confirmState.current.message }}</p>
    <template #foot>
      <button type="button" class="btn" @click="confirmState.current.resolve(false)">Hủy</button>
      <button
        type="button"
        class="btn primary"
        :style="confirmState.current.danger ? 'background: var(--danger-text); border-color: var(--danger-text)' : undefined"
        @click="confirmState.current.resolve(true)"
      >
        {{ confirmState.current.okLabel }}
      </button>
    </template>
  </Modal>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { GRIP, ICONS } from '../lib/icons';

const props = withDefaults(defineProps<{ name: string; size?: number }>(), { size: 18 });
const body = computed(() => (props.name === 'grip' ? GRIP : ICONS[props.name] || ICONS.gauge));
const style = computed(() => (props.size === 18 ? undefined : { width: `${props.size}px`, height: `${props.size}px` }));
</script>

<template>
  <svg class="ic" :class="{ fill: name === 'grip' }" viewBox="0 0 24 24" aria-hidden="true" :style="style" v-html="body" />
</template>

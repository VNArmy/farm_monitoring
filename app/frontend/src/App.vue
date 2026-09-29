<script setup lang="ts">
// Gốc web app: trang đăng nhập đứng riêng; các trang khác nằm trong khung có luồng trực tiếp SSE.
import { computed, provide, watch } from 'vue';
import { RouterLink, RouterView, useRoute } from 'vue-router';
import AppShell from './components/AppShell.vue';
import UiHost from './components/UiHost.vue';
import { LIVE, createLive } from './lib/live';
import { MAIN_NAV } from './lib/nav';
import { isAdmin, session } from './lib/session';

const route = useRoute();
const live = createLive({
  overviewUrl: '/api/overview',
  streamUrl: () => '/api/stream',
  sparkUrl: '/api/sparklines',
});
provide(LIVE, live);

watch(
  () => session.me,
  (me) => {
    if (me) live.start();
  },
  { immediate: true },
);

const bare = computed(() => route.meta.public === true || !session.me);
const blocked = computed(() => route.meta.admin === true && !isAdmin());
</script>

<template>
  <RouterView v-if="bare" />
  <AppShell v-else :nav="MAIN_NAV" :admin="isAdmin()">
    <div v-if="blocked" class="empty" style="max-width: 560px">
      <h2>Chỉ dành cho quản trị viên</h2>
      <p>Tài khoản của bạn chỉ xem được số liệu, biểu đồ và xuất CSV.</p>
      <RouterLink class="btn" to="/">Về Tổng quan</RouterLink>
    </div>
    <RouterView v-else v-slot="{ Component }">
      <component :is="Component" :key="route.path" />
    </RouterView>
  </AppShell>
  <UiHost />
</template>

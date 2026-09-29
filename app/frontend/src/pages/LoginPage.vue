<script setup lang="ts">
// Đăng nhập: tối đa 5 lần sai mỗi 10 phút cho mỗi IP; server báo số lần thử còn lại.
import { nextTick, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import Icon from '../components/Icon.vue';
import { ApiError, api } from '../lib/api';
import { setMe } from '../lib/session';
import type { Me } from '../lib/types';

const route = useRoute();
const router = useRouter();
const site = ref('');
const username = ref('');
const password = ref('');
const show = ref(false);
const busy = ref(false);
const error = ref('');
const userEl = ref<HTMLInputElement>();
const passEl = ref<HTMLInputElement>();

onMounted(async () => {
  userEl.value?.focus();
  try {
    site.value = (await api.get<{ site_name: string }>('/api/auth/site')).site_name;
  } catch {
    // không bắt buộc
  }
});

async function submit(): Promise<void> {
  error.value = '';
  if (!username.value.trim() || !password.value) {
    error.value = 'Nhập tên đăng nhập và mật khẩu.';
    return;
  }
  busy.value = true;
  try {
    const me = await api.post<Me>('/api/auth/login', { username: username.value.trim(), password: password.value });
    setMe(me);
    const next = typeof route.query.next === 'string' ? route.query.next : '';
    await router.replace(next.startsWith('/') && !next.startsWith('//') && next !== '/dang-nhap' ? next : '/');
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : String(e);
    await nextTick();
    passEl.value?.select();
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-col">
      <div class="login-brand">
        <div class="logo"><Icon name="logo" :size="28" /></div>
        <div class="col gap-4">
          <div style="font-size: 20px; line-height: 28px; font-weight: 600">Giám sát nhà kính</div>
          <div class="text-3">{{ site }}</div>
        </div>
      </div>
      <form class="login-form" novalidate @submit.prevent="submit">
        <h1>Đăng nhập</h1>
        <div v-if="error" id="loi-dang-nhap" class="banner danger sm" role="alert">
          <Icon name="xCircle" />
          <div>{{ error }}</div>
        </div>
        <div class="field">
          <label for="dn-ten" style="font-size: 14px">Tên đăng nhập</label>
          <input
            id="dn-ten"
            ref="userEl"
            v-model="username"
            class="input lg"
            type="text"
            autocomplete="username"
            autocapitalize="none"
            spellcheck="false"
            required
          />
        </div>
        <div class="field">
          <label for="dn-mk" style="font-size: 14px">Mật khẩu</label>
          <div class="affix lg" :class="{ invalid: !!error }">
            <input
              id="dn-mk"
              ref="passEl"
              v-model="password"
              :type="show ? 'text' : 'password'"
              autocomplete="current-password"
              required
              :aria-invalid="error ? 'true' : undefined"
              :aria-describedby="error ? 'loi-dang-nhap' : undefined"
            />
            <button
              type="button"
              class="icon-btn"
              :aria-label="show ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'"
              style="width: 44px; height: 44px"
              @click="show = !show"
            >
              <Icon :name="show ? 'eyeOff' : 'eye'" />
            </button>
          </div>
        </div>
        <button type="submit" class="btn primary lg block" :class="{ busy }" :disabled="busy">Đăng nhập</button>
      </form>
      <div class="login-foot">
        <div>Quên mật khẩu? Nhờ quản trị viên đặt lại.</div>
        <div class="muted">Chỉ truy cập được trong mạng nội bộ của trang trại hoặc qua VPN.</div>
      </div>
    </div>
  </div>
</template>

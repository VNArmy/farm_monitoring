<script setup lang="ts">
// Tài khoản: đổi mật khẩu (bắt buộc khi đăng nhập bằng mật khẩu tạm), đăng xuất, lối vào trang quản trị trên điện thoại.
import { computed, reactive, ref } from 'vue';
import { RouterLink, useRouter } from 'vue-router';
import Icon from '../components/Icon.vue';
import { api } from '../lib/api';
import { initials } from '../lib/format';
import { ADMIN_NAV } from '../lib/nav';
import { ROLE_NAMES, logout, session, setMe } from '../lib/session';
import type { Me } from '../lib/types';
import { toast, useFormErrors } from '../lib/ui';

const router = useRouter();
const me = computed(() => session.me);
const forced = computed(() => !!me.value?.user.must_change_password);
const form = reactive({ current: '', new: '', again: '' });
const busy = ref(false);
const { errors, clear, fail } = useFormErrors();

async function submit(): Promise<void> {
  clear();
  if (form.new.length < 10) {
    errors.new = 'Mật khẩu mới cần tối thiểu 10 ký tự';
    return;
  }
  if (form.new !== form.again) {
    errors.again = 'Hai lần nhập mật khẩu mới không khớp';
    return;
  }
  busy.value = true;
  try {
    const wasForced = forced.value;
    setMe(await api.post<Me>('/api/auth/password', { current: form.current, new: form.new }));
    toast('Đã đổi mật khẩu. Các phiên đăng nhập khác đã bị đăng xuất.');
    form.current = form.new = form.again = '';
    if (wasForced) await router.replace('/');
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="col gap-20">
    <div class="page-head hide-phone">
      <div>
        <h1>Tài khoản</h1>
        <div class="page-sub">Thông tin đăng nhập và đổi mật khẩu</div>
      </div>
    </div>
    <div v-if="forced" class="banner warn">
      <Icon name="key" :size="20" />
      <div class="body"><span class="strong">Bạn đang dùng mật khẩu tạm.</span> Đổi mật khẩu trước khi tiếp tục.</div>
    </div>
    <div class="split w420">
      <div class="col gap-16">
        <section class="panel p20">
          <div class="row">
            <span class="avatar" style="width: 44px; height: 44px; border-radius: 22px; font-size: 15px">{{ initials(me?.user.username) }}</span>
            <div class="col grow">
              <span class="strong" style="font-size: 16px">{{ me?.user.username }}</span>
              <span class="fs-13 muted">{{ ROLE_NAMES[me?.user.role ?? ''] }}</span>
            </div>
            <button type="button" class="btn sm" @click="logout"><Icon name="logout" />Đăng xuất</button>
          </div>
        </section>
        <form class="panel p20" novalidate @submit.prevent="submit">
          <h2 class="panel-title sm">Đổi mật khẩu</h2>
          <div class="field">
            <label for="pw-cur">Mật khẩu hiện tại</label>
            <input
              id="pw-cur"
              v-model="form.current"
              data-field="current"
              class="input"
              :class="{ invalid: errors.current }"
              type="password"
              autocomplete="current-password"
              required
              @input="clear('current')"
            />
            <span v-if="errors.current" class="hint err">{{ errors.current }}</span>
          </div>
          <div class="field">
            <label for="pw-new">Mật khẩu mới</label>
            <input
              id="pw-new"
              v-model="form.new"
              data-field="new"
              class="input"
              :class="{ invalid: errors.new }"
              type="password"
              autocomplete="new-password"
              minlength="10"
              required
              @input="clear('new')"
            />
            <span class="hint" :class="{ err: errors.new }">{{ errors.new || 'Tối thiểu 10 ký tự' }}</span>
          </div>
          <div class="field">
            <label for="pw-new2">Nhập lại mật khẩu mới</label>
            <input
              id="pw-new2"
              v-model="form.again"
              data-field="again"
              class="input"
              :class="{ invalid: errors.again }"
              type="password"
              autocomplete="new-password"
              required
              @input="clear('again')"
            />
            <span v-if="errors.again" class="hint err">{{ errors.again }}</span>
          </div>
          <div class="row" style="justify-content: flex-end">
            <button type="submit" class="btn primary" :class="{ busy }" :disabled="busy">Đổi mật khẩu</button>
          </div>
        </form>
      </div>
      <section v-if="me?.user.role === 'admin' && !forced" class="panel p20">
        <h2 class="panel-title sm">Quản trị</h2>
        <div class="col gap-4">
          <RouterLink v-for="n in ADMIN_NAV" :key="n.id" class="nav-link" :to="n.to">
            <Icon :name="n.icon" :size="20" /><span>{{ n.label }}</span><span class="ml-auto muted"><Icon name="right" :size="16" /></span>
          </RouterLink>
        </div>
      </section>
    </div>
  </div>
</template>

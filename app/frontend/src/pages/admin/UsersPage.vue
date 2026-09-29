<script setup lang="ts">
// Quản trị · Người dùng (spec mục 8.1): thêm, đổi vai trò, đặt lại mật khẩu, khóa và mở khóa; không xóa cứng.
// Khóa hoặc đổi mật khẩu thu hồi mọi phiên của người đó; không khóa hay hạ quyền admin cuối cùng.
import { onMounted, reactive, ref } from 'vue';
import FormField from '../../components/FormField.vue';
import Icon from '../../components/Icon.vue';
import Modal from '../../components/Modal.vue';
import { api } from '../../lib/api';
import { fmtDateTime, fmtWhen, initials } from '../../lib/format';
import { ROLE_NAMES } from '../../lib/session';
import type { User } from '../../lib/types';
import { attempt, confirmDialog, toast, useFormErrors } from '../../lib/ui';

const users = ref<User[] | null>(null);
const { errors, clear, fail } = useFormErrors();
const add = reactive({ open: false, username: '', role: 'viewer' as 'viewer' | 'admin', password: '', busy: false });
const reset = reactive({ open: false, user: null as User | null, password: '', busy: false, done: false });

async function load(): Promise<void> {
  users.value = await api.get<User[]>('/api/admin/users');
}

async function suggest(): Promise<string> {
  try {
    return (await api.get<{ password: string }>('/api/admin/users/temp-password')).password;
  } catch {
    return '';
  }
}

async function openAdd(): Promise<void> {
  clear();
  Object.assign(add, { open: true, username: '', role: 'viewer', password: await suggest(), busy: false });
}

async function submitAdd(): Promise<void> {
  clear();
  add.busy = true;
  try {
    const u = await api.post<User>('/api/admin/users', { username: add.username.trim().toLowerCase(), role: add.role, password: add.password });
    toast(`Đã thêm ${u.username}. Gửi mật khẩu tạm cho người đó; lần đăng nhập đầu phải đổi mật khẩu.`);
    add.open = false;
    await load();
  } catch (e) {
    fail(e);
  } finally {
    add.busy = false;
  }
}

async function patch(u: User, body: { role?: string; is_active?: boolean }, msg: string): Promise<void> {
  const r = await attempt(() => api.patch<User>(`/api/admin/users/${u.id}`, body));
  if (r) {
    toast(msg);
    await load();
  }
}

async function setRole(u: User, role: 'admin' | 'viewer'): Promise<void> {
  if (role === u.role) return;
  const ok = await confirmDialog(
    'Đổi vai trò',
    `Đổi ${u.username} thành ${ROLE_NAMES[role]}? Các phiên đăng nhập hiện tại của người đó sẽ bị đăng xuất.`,
    'Đổi vai trò',
  );
  if (ok) await patch(u, { role }, `${u.username} giờ là ${ROLE_NAMES[role]}`);
  else await load();
}

async function toggleActive(u: User): Promise<void> {
  if (u.is_active) {
    const ok = await confirmDialog('Khóa tài khoản', `Khóa ${u.username}? Người đó bị đăng xuất ngay và không đăng nhập được nữa.`, 'Khóa', true);
    if (!ok) return;
  }
  await patch(u, { is_active: !u.is_active }, u.is_active ? `Đã khóa ${u.username}` : `Đã mở khóa ${u.username}`);
}

async function openReset(u: User): Promise<void> {
  clear();
  Object.assign(reset, { open: true, user: u, password: await suggest(), busy: false, done: false });
}

async function submitReset(): Promise<void> {
  const u = reset.user;
  if (!u) return;
  clear();
  reset.busy = true;
  try {
    await api.post(`/api/admin/users/${u.id}/reset-password`, { password: reset.password });
    reset.done = true;
    toast(`Đã đặt lại mật khẩu cho ${u.username}`);
    await load();
  } catch (e) {
    fail(e);
  } finally {
    reset.busy = false;
  }
}

async function copy(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    toast('Đã chép mật khẩu');
  } catch {
    toast('Trình duyệt không cho chép; hãy chọn và chép thủ công', 'err');
  }
}

onMounted(() => void attempt(load));
</script>

<template>
  <div class="col gap-20">
    <div class="page-head">
      <div class="title-block">
        <h1>Người dùng</h1>
        <div class="page-sub">Quản trị viên cấu hình hệ thống; người xem chỉ xem số liệu, biểu đồ và xuất CSV</div>
      </div>
      <button type="button" class="btn primary" @click="openAdd"><Icon name="plus" />Thêm người dùng</button>
    </div>

    <div v-if="!users" class="loading"><div class="spinner" role="status" aria-label="Đang tải" /></div>
    <div v-else class="tbl-wrap">
      <table class="tbl">
        <thead>
          <tr><th>Người dùng</th><th>Vai trò</th><th>Trạng thái</th><th>Đăng nhập gần nhất</th><th>Tạo lúc</th><th /></tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id" :class="{ 'muted-row': !u.is_active }">
            <td>
              <span class="row gap-10">
                <span class="avatar" :class="{ neutral: u.role !== 'admin' }">{{ initials(u.username) }}</span>
                <span class="col">
                  <span class="strong">{{ u.username }}{{ u.is_me ? ' (bạn)' : '' }}</span>
                  <span v-if="u.must_change_password" class="small muted">Đang dùng mật khẩu tạm</span>
                </span>
              </span>
            </td>
            <td>
              <select
                class="input sm"
                style="width: 150px"
                :value="u.role"
                :aria-label="`Vai trò của ${u.username}`"
                @change="setRole(u, ($event.target as HTMLSelectElement).value as 'admin' | 'viewer')"
              >
                <option value="viewer">{{ ROLE_NAMES.viewer }}</option>
                <option value="admin">{{ ROLE_NAMES.admin }}</option>
              </select>
            </td>
            <td>
              <span class="badge" :class="u.is_active ? 'ok' : 'off'">{{ u.is_active ? 'Hoạt động' : 'Đã khóa' }}</span>
            </td>
            <td class="tn">{{ u.last_login_at ? fmtWhen(u.last_login_at) : 'Chưa đăng nhập' }}</td>
            <td class="tn muted">{{ fmtDateTime(u.created_at) }}</td>
            <td class="num nowrap">
              <button type="button" class="btn sm ghost" @click="openReset(u)"><Icon name="key" />Đặt lại mật khẩu</button>
              <button v-if="!u.is_me" type="button" class="btn sm ghost" @click="toggleActive(u)">
                <Icon :name="u.is_active ? 'lock' : 'key'" />{{ u.is_active ? 'Khóa' : 'Mở khóa' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <Modal v-if="add.open" title="Thêm người dùng" size="sm" @close="add.open = false">
      <form id="f-add" class="col gap-16" novalidate @submit.prevent="submitAdd">
        <FormField label="Tên đăng nhập" input-id="u-ten" :error="errors.username" hint="3–32 ký tự: chữ thường không dấu, số, gạch dưới">
          <input
            id="u-ten"
            v-model="add.username"
            data-field="username"
            class="input"
            :class="{ invalid: errors.username }"
            autocapitalize="none"
            spellcheck="false"
            autocomplete="off"
          />
        </FormField>
        <fieldset class="col gap-8">
          <legend>Vai trò</legend>
          <label class="choice" :class="{ on: add.role === 'viewer' }">
            <input v-model="add.role" type="radio" value="viewer" />
            <span><b>Người xem</b><small>Xem tổng quan, biểu đồ, xuất CSV</small></span>
          </label>
          <label class="choice" :class="{ on: add.role === 'admin' }">
            <input v-model="add.role" type="radio" value="admin" />
            <span><b>Quản trị viên</b><small>Thêm cả cấu hình kết nối, thiết bị, người dùng, cài đặt</small></span>
          </label>
        </fieldset>
        <FormField label="Mật khẩu tạm" input-id="u-mk" :error="errors.password" hint="Tối thiểu 10 ký tự; người dùng phải đổi ở lần đăng nhập đầu">
          <div class="row gap-8">
            <input id="u-mk" v-model="add.password" data-field="password" class="input mono grow" :class="{ invalid: errors.password }" autocomplete="off" />
            <button type="button" class="btn icon" aria-label="Chép mật khẩu" @click="copy(add.password)"><Icon name="copy" /></button>
          </div>
        </FormField>
      </form>
      <template #foot>
        <button type="button" class="btn" @click="add.open = false">Hủy</button>
        <button type="submit" form="f-add" class="btn primary" :class="{ busy: add.busy }" :disabled="add.busy">Thêm người dùng</button>
      </template>
    </Modal>

    <Modal v-if="reset.open && reset.user" :title="`Đặt lại mật khẩu · ${reset.user.username}`" size="sm" @close="reset.open = false">
      <template v-if="!reset.done">
        <p class="text-3" style="margin: 0">
          Mọi phiên đăng nhập của {{ reset.user.username }} bị đăng xuất; lần đăng nhập tới phải đổi mật khẩu.
        </p>
        <FormField label="Mật khẩu tạm" input-id="r-mk" :error="errors.password" hint="Tối thiểu 10 ký tự">
          <div class="row gap-8">
            <input id="r-mk" v-model="reset.password" data-field="password" class="input mono grow" :class="{ invalid: errors.password }" autocomplete="off" />
            <button type="button" class="btn icon" aria-label="Chép mật khẩu" @click="copy(reset.password)"><Icon name="copy" /></button>
          </div>
        </FormField>
      </template>
      <div v-else class="banner ok sm">
        <Icon name="check" />
        <div>
          Đã đặt mật khẩu tạm <span class="mono strong">{{ reset.password }}</span>. Gửi cho {{ reset.user.username }} qua kênh riêng.
        </div>
      </div>
      <template #foot>
        <button type="button" class="btn" @click="reset.open = false">{{ reset.done ? 'Đóng' : 'Hủy' }}</button>
        <button v-if="!reset.done" type="button" class="btn primary" :class="{ busy: reset.busy }" :disabled="reset.busy" @click="submitReset">
          Đặt lại mật khẩu
        </button>
      </template>
    </Modal>
  </div>
</template>

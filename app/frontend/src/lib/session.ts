// Người dùng đang đăng nhập và CSRF token (GET /api/auth/me).
import { reactive } from 'vue';
import { api, setCsrf } from './api';
import { setTimezone } from './format';
import type { Me } from './types';

export const session = reactive<{ me: Me | null; loaded: boolean }>({ me: null, loaded: false });

export function setMe(me: Me | null): void {
  session.me = me;
  session.loaded = true;
  setCsrf(me?.csrf_token ?? '');
  if (me) setTimezone(me.timezone);
}

export async function loadMe(): Promise<Me | null> {
  try {
    setMe(await api.get<Me>('/api/auth/me'));
  } catch {
    setMe(null);
  }
  return session.me;
}

export async function logout(): Promise<void> {
  try {
    await api.post('/api/auth/logout');
  } catch {
    // vẫn về trang đăng nhập
  }
  location.assign('/dang-nhap');
}

export const isAdmin = (): boolean => session.me?.user.role === 'admin';

export const ROLE_NAMES: Record<string, string> = { admin: 'Quản trị viên', viewer: 'Người xem' };

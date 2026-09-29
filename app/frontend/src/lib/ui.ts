// Thông báo nhanh, hộp xác nhận và lỗi form theo từng ô (field trong lỗi API).
import { reactive } from 'vue';

export interface Toast {
  id: number;
  message: string;
  kind: '' | 'err';
}

export const toasts = reactive<Toast[]>([]);
let toastSeq = 0;

export function toast(message: string, kind: '' | 'err' = ''): void {
  const id = ++toastSeq;
  toasts.push({ id, message, kind });
  setTimeout(
    () => {
      const i = toasts.findIndex((t) => t.id === id);
      if (i >= 0) toasts.splice(i, 1);
    },
    kind === 'err' ? 6000 : 3500,
  );
}

export interface ConfirmState {
  title: string;
  message: string;
  okLabel: string;
  danger: boolean;
  resolve: (ok: boolean) => void;
}

export const confirmState = reactive<{ current: ConfirmState | null }>({ current: null });

export function confirmDialog(title: string, message: string, okLabel = 'Đồng ý', danger = false): Promise<boolean> {
  return new Promise((resolve) => {
    confirmState.current?.resolve(false);
    confirmState.current = {
      title,
      message,
      okLabel,
      danger,
      resolve: (ok) => {
        confirmState.current = null;
        resolve(ok);
      },
    };
  });
}

/**
 * Lỗi của một form: errors[field] là thông báo hiện dưới ô đó.
 * fail(e) nhận lỗi API: có field thì gắn vào ô, không thì báo bằng toast.
 */
export function useFormErrors() {
  const errors = reactive<Record<string, string>>({});
  function clear(field?: string): void {
    if (field) delete errors[field];
    else for (const k of Object.keys(errors)) delete errors[k];
  }
  function fail(e: unknown): void {
    // Lỗi API có field, hoặc lỗi kiểm tra ngay trên form (FieldError ở lib/admin.ts)
    const field = e instanceof Error && 'field' in e && typeof e.field === 'string' ? e.field : '';
    if (field) {
      errors[field] = (e as Error).message;
      // Cuộn tới ô lỗi (thuộc tính data-field trùng tên trường)
      requestAnimationFrame(() => {
        const el = document.querySelector<HTMLElement>(`[data-field="${CSS.escape(field)}"]`);
        el?.scrollIntoView({ block: 'center', behavior: 'smooth' });
        el?.focus?.({ preventScroll: true });
      });
    } else {
      toast(e instanceof Error ? e.message : String(e), 'err');
    }
  }
  return { errors, clear, fail };
}

/** Chạy một thao tác, báo lỗi bằng toast; trả về undefined khi lỗi. */
export async function attempt<T>(fn: () => Promise<T>): Promise<T | undefined> {
  try {
    return await fn();
  } catch (e) {
    toast(e instanceof Error ? e.message : String(e), 'err');
    return undefined;
  }
}

export const local = {
  get<T>(key: string, fallback: T): T {
    try {
      const v = localStorage.getItem(key);
      return v == null ? fallback : (JSON.parse(v) as T);
    } catch {
      return fallback;
    }
  },
  set(key: string, value: unknown): void {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // chế độ riêng tư
    }
  },
};

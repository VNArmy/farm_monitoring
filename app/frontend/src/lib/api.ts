// Gọi API: JSON, cookie session, header X-CSRF-Token cho request ghi (spec mục 9).
// Lỗi từ server có dạng {"error": {"code", "message", "field"}}; field để form báo lỗi đúng ô.

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly field: string | null;

  constructor(status: number, code: string, message: string, field: string | null = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.field = field;
  }
}

let csrfToken = '';
let onUnauthorized: (() => void) | null = null;

export function setCsrf(token: string): void {
  csrfToken = token;
}

export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

export async function request<T = unknown>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && method !== 'HEAD' && csrfToken) headers['X-CSRF-Token'] = csrfToken;
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'network', 'Không kết nối được tới Datalogger. Kiểm tra mạng rồi thử lại.');
  }
  const type = res.headers.get('content-type') || '';
  const data: unknown = type.includes('json') ? await res.json().catch(() => null) : await res.text();
  if (!res.ok) {
    const err = (data && typeof data === 'object' && 'error' in data ? (data as { error: unknown }).error : null) as {
      code?: string;
      message?: string;
      field?: string | null;
    } | null;
    if (res.status === 401 && !url.startsWith('/api/auth/')) onUnauthorized?.();
    throw new ApiError(
      res.status,
      err?.code ?? 'error',
      err?.message ?? (typeof data === 'string' && data ? data : res.statusText || 'Có lỗi xảy ra'),
      err?.field ?? null,
    );
  }
  return data as T;
}

export const api = {
  get: <T = unknown>(url: string) => request<T>('GET', url),
  post: <T = unknown>(url: string, body: unknown = {}) => request<T>('POST', url, body),
  put: <T = unknown>(url: string, body: unknown = {}) => request<T>('PUT', url, body),
  patch: <T = unknown>(url: string, body: unknown = {}) => request<T>('PATCH', url, body),
  del: <T = unknown>(url: string) => request<T>('DELETE', url),
};

export function qs(obj: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(obj)) if (v != null && v !== '') p.set(k, String(v));
  return p.toString();
}

/** Tải file bằng một thẻ <a> tạm (trình duyệt tự mang cookie). */
export function download(url: string): void {
  const a = document.createElement('a');
  a.href = url;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// Tiện ích dùng chung cho các trang quản trị: tên hiển thị, tóm tắt kết nối, đọc số trong form.
import { fmtNum, parseNum } from './format';
import type { Connection } from './types';

export const BAUDS = [2400, 4800, 9600, 19200, 38400, 57600, 115200];
export const PARITY_NAMES: Record<string, string> = { N: 'None', E: 'Even', O: 'Odd' };
export const CATEGORY_NAMES: Record<string, string> = {
  climate: 'Khí hậu',
  wind: 'Gió',
  light: 'Ánh sáng',
  co2: 'CO2',
  nutrient: 'Dinh dưỡng',
  other: 'Khác',
};
export const DTYPES = ['int16', 'uint16', 'int32', 'uint32', 'float32'] as const;
export const BYTE_ORDERS = ['ABCD', 'CDAB', 'BADC', 'DCBA'] as const;
export const REG_COUNT: Record<string, number> = { int16: 1, uint16: 1, int32: 2, uint32: 2, float32: 2 };
export const WORKER_STATE: Record<string, { text: string; cls: string }> = {
  running: { text: 'Đang đọc', cls: 'ok' },
  paused: { text: 'Tạm dừng', cls: 'info' },
  error: { text: 'Lỗi cổng', cls: 'danger' },
  stopped: { text: 'Đang tắt', cls: 'off' },
};
export const ERROR_KIND: Record<string, string> = {
  timeout: 'Timeout',
  crc: 'CRC',
  exception: 'Exception',
  sensor: 'Lỗi cảm biến',
  io: 'Lỗi cổng',
};

/** "9600 8N1 · timeout 500 ms" hoặc "Modbus TCP · timeout 1.000 ms". */
export function connSummary(c: Pick<Connection, 'type' | 'params'>): string {
  const p = c.params;
  if (c.type === 'rtu') return `${p.baudrate} 8${p.parity}${p.stopbits} · timeout ${fmtNum(p.timeout_ms, 0)} ms`;
  return `${p.framing === 'rtu_over_tcp' ? 'RTU over TCP' : 'Modbus TCP'} · timeout ${fmtNum(p.timeout_ms, 0)} ms`;
}

export function connTarget(c: Pick<Connection, 'type' | 'params'>): string {
  return c.type === 'rtu' ? String(c.params.port) : `${c.params.host}:${c.params.port}`;
}

/** Gợi ý quy đổi địa chỉ kiểu datasheet sang địa chỉ giao thức (spec mục 4.4). */
export function addressHint(address: number | null, fc: number): string | null {
  if (address == null || !Number.isFinite(address)) return null;
  if (fc === 3 && address >= 40001 && address <= 49999) return `${address} theo quy ước 4xxxx là địa chỉ ${address - 40001} với FC 03`;
  if (fc === 4 && address >= 30001 && address <= 39999) return `${address} theo quy ước 3xxxx là địa chỉ ${address - 30001} với FC 04`;
  return null;
}

export class FieldError extends Error {
  readonly field: string;
  constructor(field: string, message: string) {
    super(message);
    this.field = field;
  }
}

/** Đọc số từ ô nhập; rỗng → null (khi không bắt buộc). Sai thì ném FieldError để form báo đúng ô. */
export function num(value: string | number | null | undefined, field: string, opts: { int?: boolean; required?: boolean } = {}): number | null {
  const n = parseNum(value ?? '');
  if (n == null) {
    if (opts.required) throw new FieldError(field, 'Bắt buộc nhập');
    return null;
  }
  if (Number.isNaN(n)) throw new FieldError(field, 'Nhập một số');
  if (opts.int && !Number.isInteger(n)) throw new FieldError(field, 'Nhập số nguyên');
  return n;
}

export function reqNum(value: string | number | null | undefined, field: string, int = false): number {
  return num(value, field, { int, required: true }) as number;
}

/** Số cho ô nhập: null → "". */
export const str = (v: number | null | undefined): string => (v == null ? '' : String(v));

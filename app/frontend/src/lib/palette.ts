// Màu kênh trên biểu đồ lịch sử; bản đậm cho chữ trục và vạch ngưỡng, bản nhạt cho chấm trên tooltip nền tối.

export const PALETTE = ['#C2410C', '#1D4ED8', '#0F766E', '#7C3AED', '#A16207', '#BE185D', '#4D7C0F', '#0369A1'];

const DARK: Record<string, string> = {
  '#C2410C': '#9A3A0A',
  '#1D4ED8': '#1E40AF',
  '#0F766E': '#115E59',
  '#7C3AED': '#5B21B6',
  '#A16207': '#854D0E',
  '#BE185D': '#9D174D',
  '#4D7C0F': '#3F6212',
  '#0369A1': '#075985',
};

const LIGHT: Record<string, string> = {
  '#C2410C': '#F08A55',
  '#1D4ED8': '#7FA2F5',
  '#0F766E': '#5EC4B6',
  '#7C3AED': '#B79CF5',
  '#A16207': '#E5B458',
  '#BE185D': '#F07AB0',
  '#4D7C0F': '#A3CF5E',
  '#0369A1': '#6BB8E8',
};

export const darkOf = (c: string | undefined): string => (c && DARK[c]) || '#52554F';
export const lightOf = (c: string | undefined): string => (c && LIGHT[c]) || '#CFCCC1';

/** Giữ màu cũ của kênh đã chọn, kênh mới lấy màu đầu tiên chưa dùng. */
export function assignColors(ids: number[], prev: Record<number, string>): Record<number, string> {
  const used = new Set<string>();
  const next: Record<number, string> = {};
  for (const id of ids) {
    const c = prev[id];
    if (c && !used.has(c)) {
      next[id] = c;
      used.add(c);
    }
  }
  for (const id of ids) {
    if (next[id]) continue;
    const c = PALETTE.find((x) => !used.has(x)) ?? PALETTE[0];
    next[id] = c;
    used.add(c);
  }
  return next;
}

/** rgba từ màu #RRGGBB. */
export function alpha(hex: string, a: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

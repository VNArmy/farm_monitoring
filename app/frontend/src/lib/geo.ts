// Tọa độ trại: tách chuỗi "vĩ độ, kinh độ" do admin dán từ app bản đồ khác, và định dạng để dán ngược lại.

export interface LatLng {
  lat: number;
  lng: number;
}

/** minLon, minLat, maxLon, maxLat */
export type Bounds = [number, number, number, number];

const PATTERN = /^(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)$/;
// 6 chữ số sau dấu chấm là khoảng 0,1 m; làm tròn để giá trị lưu trùng với giá trị hiện trên ô nhập.
const round6 = (v: number): number => Math.round(v * 1e6) / 1e6;

/** Trả về tọa độ, hoặc câu báo lỗi để hiện ngay tại ô nhập. */
export function parseLatLng(text: string): LatLng | string {
  const m = text.trim().match(PATTERN);
  if (!m) return 'Cần đủ vĩ độ và kinh độ, dùng dấu chấm thập phân, ví dụ 11.940000, 108.440000';
  const lat = Number(m[1]);
  const lng = Number(m[2]);
  if (lat < -90 || lat > 90) return 'Vĩ độ phải từ -90 đến 90';
  if (lng < -180 || lng > 180) return 'Kinh độ phải từ -180 đến 180';
  return { lat: round6(lat), lng: round6(lng) };
}

export function fmtLatLng(p: LatLng): string {
  return `${p.lat.toFixed(6)}, ${p.lng.toFixed(6)}`;
}

export function inBounds(p: LatLng, b: Bounds): boolean {
  return p.lng >= b[0] && p.lat >= b[1] && p.lng <= b[2] && p.lat <= b[3];
}

/** Khung 1° × 1° quanh trại, đúng dạng tham số --bbox của pmtiles extract. */
export function bboxAround(p: LatLng): string {
  return [p.lng - 0.5, p.lat - 0.5, p.lng + 0.5, p.lat + 0.5].map((v) => v.toFixed(6)).join(',');
}

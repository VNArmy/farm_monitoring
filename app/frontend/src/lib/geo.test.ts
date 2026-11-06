import { describe, expect, it } from 'vitest';
import { bboxAround, fmtLatLng, inBounds, parseLatLng } from './geo';

describe('parseLatLng', () => {
  it('nhận chuỗi dán từ app bản đồ', () => {
    expect(parseLatLng('11.94, 108.44')).toEqual({ lat: 11.94, lng: 108.44 });
    expect(parseLatLng('  11.94,108.44  ')).toEqual({ lat: 11.94, lng: 108.44 });
    expect(parseLatLng('11.94 108.44')).toEqual({ lat: 11.94, lng: 108.44 });
    expect(parseLatLng('11.94; 108.44')).toEqual({ lat: 11.94, lng: 108.44 });
    expect(parseLatLng('-33.8, -70')).toEqual({ lat: -33.8, lng: -70 });
  });

  it('nhận đúng biên', () => {
    expect(parseLatLng('90, 180')).toEqual({ lat: 90, lng: 180 });
    expect(parseLatLng('-90, -180')).toEqual({ lat: -90, lng: -180 });
  });

  it('làm tròn 6 chữ số để lưu lại không đổi giá trị', () => {
    const p = parseLatLng('11.94000049, 108.44000051');
    expect(p).toEqual({ lat: 11.94, lng: 108.440001 });
    expect(parseLatLng(fmtLatLng(p as { lat: number; lng: number }))).toEqual(p);
  });

  it('báo lỗi khi vượt khoảng', () => {
    expect(parseLatLng('91, 108')).toContain('Vĩ độ');
    expect(parseLatLng('-90.1, 108')).toContain('Vĩ độ');
    expect(parseLatLng('11, 181')).toContain('Kinh độ');
    // Đảo thứ tự: kinh độ đứng trước
    expect(parseLatLng('108.44, 11.94')).toContain('Vĩ độ');
  });

  it('báo lỗi khi thiếu hoặc sai dạng', () => {
    for (const text of ['', '11.94', '11.94,', 'abc, def', '11,94, 108,44', '11.94, 108.44, 3', `11°56'N 108°26'E`]) {
      expect(parseLatLng(text)).toContain('Cần đủ');
    }
  });
});

describe('định dạng và khung', () => {
  it('6 chữ số, dấu chấm thập phân', () => {
    expect(fmtLatLng({ lat: 11.94, lng: 108.44 })).toBe('11.940000, 108.440000');
  });

  it('kiểm tra điểm trong khung, gồm cả biên', () => {
    const b: [number, number, number, number] = [108, 11, 109, 12];
    expect(inBounds({ lat: 11.5, lng: 108.5 }, b)).toBe(true);
    expect(inBounds({ lat: 11, lng: 109 }, b)).toBe(true);
    expect(inBounds({ lat: 10.99, lng: 108.5 }, b)).toBe(false);
    expect(inBounds({ lat: 11.5, lng: 109.01 }, b)).toBe(false);
  });

  it('khung 1° × 1° theo thứ tự của --bbox', () => {
    expect(bboxAround({ lat: 11.94, lng: 108.44 })).toBe('107.940000,11.440000,108.940000,12.440000');
  });
});

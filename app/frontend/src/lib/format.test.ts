import { beforeEach, describe, expect, it } from 'vitest';
import {
  fmtAuto,
  fmtBytes,
  fmtDuration,
  fmtHM,
  fmtNum,
  fmtTime,
  fromLocalInput,
  parseNum,
  setTimezone,
  toLocalInput,
  tzOffsetMs,
} from './format';

describe('định dạng số tiếng Việt', () => {
  it('dấu chấm nghìn, dấu phẩy thập phân', () => {
    expect(fmtNum(38200, 0)).toBe('38.200');
    expect(fmtNum(33.8, 1)).toBe('33,8');
    expect(fmtNum(71.4, 1)).toBe('71,4');
    expect(fmtNum(3.4, 1)).toBe('3,4');
    expect(fmtNum(612, 0)).toBe('612');
    expect(fmtNum(-2.25, 2)).toBe('-2,25');
    expect(fmtNum(null)).toBe('—');
    expect(fmtNum(Number.NaN)).toBe('—');
  });

  it('số tự đủ chữ số lẻ', () => {
    expect(fmtAuto(0.1)).toBe('0,1');
    expect(fmtAuto(2.5)).toBe('2,5');
    expect(fmtAuto(100000)).toBe('100.000');
    expect(fmtAuto(null)).toBe('');
  });

  it('đọc số người dùng gõ', () => {
    expect(parseNum('33,8')).toBe(33.8);
    expect(parseNum('33.8')).toBe(33.8);
    expect(parseNum('38.200')).toBe(38200);
    expect(parseNum('1.234,5')).toBe(1234.5);
    expect(parseNum('-40')).toBe(-40);
    expect(parseNum(' ')).toBeNull();
    expect(parseNum('abc')).toBeNaN();
  });

  it('dung lượng và khoảng thời gian', () => {
    expect(fmtBytes(1_500_000)).toBe('1,5 MB');
    expect(fmtBytes(250_000_000_000)).toBe('250 GB');
    expect(fmtDuration(3 * 3600 + 30 * 60)).toBe('3 giờ 30 phút');
    expect(fmtDuration(45)).toBe('45 giây');
  });
});

describe('thời gian theo múi giờ của site', () => {
  beforeEach(() => setTimezone('Asia/Ho_Chi_Minh'));
  const ts = Date.UTC(2026, 8, 29, 7, 32, 5); // 14:32:05 giờ Việt Nam

  it('hiện giờ Việt Nam', () => {
    expect(fmtTime(ts)).toBe('14:32:05');
    expect(fmtHM(ts)).toBe('14:32');
    expect(tzOffsetMs(ts)).toBe(7 * 3_600_000);
  });

  it('ô datetime-local hai chiều', () => {
    expect(toLocalInput(ts)).toBe('2026-09-29T14:32');
    expect(fromLocalInput('2026-09-29T14:32')).toBe(ts - 5000);
  });
});

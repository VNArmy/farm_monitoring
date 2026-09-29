import { describe, expect, it } from 'vitest';
import { align, decimalsOfStep, nearest, uniqueGaps, unitsOf, yRange } from './chartdata';
import type { History, Series } from './types';

function series(over: Partial<Series>): Series {
  return {
    channel_id: 1,
    label: 'Nhiệt độ',
    unit: '°C',
    zone: 'Nhà kính 1',
    device_name: 'Node 02',
    decimals: 1,
    alarm_low: null,
    alarm_high: null,
    interval_ms: 60_000,
    points: [],
    gaps: [],
    stats: null,
    ...over,
  };
}

describe('align', () => {
  it('gộp trục thời gian, kênh thiếu điểm là undefined, đầu khoảng mất dữ liệu là null', () => {
    const d: History = {
      from: 0,
      to: 600_000,
      bucket_ms: 60_000,
      max_points: 2000,
      series: [
        series({
          channel_id: 1,
          points: [
            [0, 30, 29, 31],
            [60_000, 31, 30, 32],
            [300_000, 33, 32, 34],
          ],
          gaps: [[120_000, 300_000]],
        }),
        series({ channel_id: 2, unit: '%RH', points: [[60_000, 70, 69, 71]] }),
      ],
    };
    const a = align(d);
    expect(a.xs).toEqual([0, 60, 120, 300]);
    expect(a.avg[0]).toEqual([30, 31, null, 33]);
    expect(a.min[0]).toEqual([29, 30, null, 32]);
    expect(a.avg[1]).toEqual([undefined, 70, undefined, undefined]);
  });
});

describe('yRange', () => {
  it('chứa dải thấp nhất–cao nhất và ngưỡng gần dữ liệu, số không âm không xuống dưới 0', () => {
    const s = series({
      points: [
        [0, 5, 0.2, 10],
        [60_000, 6, 2, 9],
      ],
      alarm_high: 12,
      alarm_low: 1000,
    });
    const [lo, hi] = yRange([s], true);
    expect(lo).toBe(0);
    expect(hi).toBeGreaterThan(12);
    expect(hi).toBeLessThan(20);
  });

  it('không có điểm thì trả 0–1; giá trị phẳng thì nới ra', () => {
    expect(yRange([series({})], true)).toEqual([0, 1]);
    const [lo, hi] = yRange([series({ points: [[0, -5, -5, -5]] })], false);
    expect(lo).toBeLessThan(-5);
    expect(hi).toBeGreaterThan(-5);
  });
});

describe('tiện ích', () => {
  it('decimalsOfStep', () => {
    expect(decimalsOfStep(20)).toBe(0);
    expect(decimalsOfStep(0.5)).toBe(1);
    expect(decimalsOfStep(0.25)).toBe(2);
    expect(decimalsOfStep(0.1 + 0.2)).toBe(1);
  });

  it('nearest', () => {
    const pts: [number, number][] = [
      [0, 1],
      [10, 2],
      [20, 3],
    ];
    expect(nearest(pts, 14)).toBe(1);
    expect(nearest(pts, 16)).toBe(2);
    expect(nearest([], 5)).toBe(-1);
  });

  it('unitsOf tối đa 2 đơn vị', () => {
    expect(unitsOf([{ unit: '°C' }, { unit: '%RH' }, { unit: '°C' }, { unit: 'lux' }])).toEqual(['°C', '%RH']);
  });

  it('uniqueGaps: một node mất kết nối chỉ tính một lần, khoảng dài nhất trước', () => {
    const a = series({ channel_id: 1, gaps: [[0, 100]] });
    const b = series({ channel_id: 2, gaps: [[0, 100]] });
    const c = series({ channel_id: 3, device_name: 'Node 01', gaps: [[0, 500]] });
    const g = uniqueGaps([a, b, c]);
    expect(g).toHaveLength(2);
    expect(g[0].device).toBe('Node 01');
  });
});

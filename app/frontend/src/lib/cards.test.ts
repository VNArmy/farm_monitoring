import { describe, expect, it } from 'vitest';
import { cardView, sparkPath } from './cards';
import { addressHint } from './admin';
import type { Metric } from './types';

const base: Metric = {
  id: 1,
  key: 'temperature',
  label: 'Nhiệt độ',
  unit: '°C',
  zone: 'Nhà kính 1',
  device_id: 2,
  device_name: 'Node 02 · Nhiệt ẩm',
  decimals: 1,
  estimate: false,
  note: '',
  display_min: 0,
  display_max: 50,
  alarm_low: 15,
  alarm_high: 35,
  poll_s: 10,
  value: 33.8,
  ts: 1_780_000_000_000,
  state: 'ok',
};

describe('cardView (bảng trạng thái spec mục 7)', () => {
  it('bình thường: số định dạng Việt Nam, chân thẻ là ngưỡng', () => {
    const v = cardView(base);
    expect(v.cls).toBe('');
    expect(v.value).toBe('33,8');
    expect(v.footL).toBe('Ngưỡng 15–35 °C');
  });

  it('vượt ngưỡng cao', () => {
    const v = cardView({ ...base, value: 36.2, state: 'alarm', alarm: 'high' });
    expect(v.cls).toBe('warn');
    expect(v.badge?.text).toBe('Vượt ngưỡng');
    expect(v.threshold).toBe(35);
  });

  it('lỗi cảm biến và mất kết nối không hiện số', () => {
    expect(cardView({ ...base, state: 'fault', detail: 'Node báo mã lỗi -32768' }).value).toBe('—');
    expect(cardView({ ...base, state: 'fault', detail: 'Node báo mã lỗi -32768' }).footL).toBe('Node 02 báo mã lỗi -32768');
    expect(cardView({ ...base, state: 'offline' }).value).toBe('—');
  });

  it('chưa có lần đọc nào: Đang chờ dữ liệu thay cho ô trống hay số 0', () => {
    const v = cardView({ ...base, value: null, ts: null, state: 'nodata' });
    expect(v.waiting).toBe(true);
  });

  it('kênh ước tính có nhãn Ước tính', () => {
    expect(cardView({ ...base, key: 'co2', unit: 'ppm', estimate: true }).badge?.text).toBe('Ước tính');
  });
});

describe('sparkPath', () => {
  it('ngắt nét ở khoảng trống dài hơn gapMs', () => {
    const d = sparkPath(
      [
        [0, 1],
        [60_000, 2],
        [600_000, 3],
      ],
      0,
      600_000,
      0,
      4,
      200,
      48,
      180_000,
    );
    expect(d.match(/M/g)).toHaveLength(2);
  });
});

describe('addressHint', () => {
  it('quy đổi 40001 và 30010', () => {
    expect(addressHint(40001, 3)).toContain('địa chỉ 0 với FC 03');
    expect(addressHint(30010, 4)).toContain('địa chỉ 9 với FC 04');
    expect(addressHint(30010, 3)).toBeNull();
  });
});

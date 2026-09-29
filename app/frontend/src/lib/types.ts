// Kiểu dữ liệu của ảnh chụp trạng thái (GET /api/overview, sự kiện SSE) và các trang quản trị.

export type ChannelState = 'ok' | 'alarm' | 'stale' | 'fault' | 'offline' | 'disabled' | 'nodata' | 'out_of_range';

/** Thứ hiện được trên thẻ: kênh đo hoặc chỉ số dẫn xuất (VPD). */
export interface Metric {
  id: number | string;
  key: string;
  label: string;
  unit: string;
  zone: string;
  device_id: number;
  device_name: string;
  decimals: number;
  estimate: boolean;
  note: string;
  display_min: number | null;
  display_max: number | null;
  alarm_low: number | null;
  alarm_high: number | null;
  poll_s: number;
  value: number | null;
  ts: number | null;
  state: ChannelState;
  alarm?: 'high' | 'low' | null;
  alarm_since?: number | null;
  fault_since?: number | null;
  offline_since?: number | null;
  detail?: string | null;
}

export interface Channel extends Metric {
  id: number;
  connection_name: string | null;
  order: number;
  valid_min: number | null;
  valid_max: number | null;
  quality: string | null;
}

export interface Derived extends Metric {
  id: string;
  kind: 'vpd';
  inputs: [number, number];
}

export type DeviceState = 'online' | 'offline' | 'stale' | 'unknown' | 'disabled';

export interface Device {
  id: number;
  name: string;
  zone: string;
  connection_id: number | null;
  connection_name: string | null;
  unit_id: number;
  poll_s: number;
  state: DeviceState;
  since: number | null;
  rtt_ms: number | null;
  last_ok_at: number | null;
  last_error: string | null;
}

export interface Zone {
  name: string;
  channels: number[];
  devices: number[];
  connections: string[];
}

export interface Alarm {
  channel_id: number;
  label: string;
  zone: string;
  device_name: string;
  value: number;
  unit: string;
  decimals: number;
  kind: 'high' | 'low';
  threshold: number;
  since: number;
  advisory: boolean;
}

export interface WorkerInfo {
  connection_id: number;
  name: string;
  state: 'running' | 'paused' | 'error' | 'stopped';
  paused_reason: string | null;
  error: string | null;
  overload: string | null;
  cycle_ms: number;
  devices: number;
  heartbeat_age_s: number;
  frame_log_until: number | null;
}

export interface CollectorInfo {
  online: boolean;
  waiting: boolean;
  started_at?: number;
  last_commit_at?: number | null;
  clock_synced?: boolean | null;
  clock_warning?: string | null;
  workers?: WorkerInfo[];
}

export interface HmiCardRef {
  id: string;
  visible: boolean;
}

export interface HmiConfig {
  layout: 'cards' | 'overview';
  cards: HmiCardRef[];
  allow_charts: boolean;
  lan_url: string;
  reload_token: string;
}

export interface Snapshot {
  now: number;
  site_name: string;
  timezone: string;
  frontend_version: string;
  collector: CollectorInfo;
  zones: Zone[];
  channels: Channel[];
  derived: Derived[];
  devices: Device[];
  alarms: Alarm[];
  hmi?: HmiConfig;
}

export interface Spark {
  points: [number, number][];
  min: number | null;
  max: number | null;
}

export interface Me {
  user: { id: number; username: string; role: 'admin' | 'viewer'; must_change_password: boolean };
  csrf_token: string;
  site_name: string;
  timezone: string;
}

// --- Biểu đồ lịch sử --------------------------------------------------------------------------

export interface Series {
  channel_id: number;
  label: string;
  unit: string;
  zone: string;
  device_name: string;
  decimals: number;
  alarm_low: number | null;
  alarm_high: number | null;
  interval_ms: number;
  points: [number, number, number, number][]; // mốc, trung bình, thấp nhất, cao nhất
  gaps: [number, number][];
  stats: { min: number; max: number; avg: number } | null;
}

export interface History {
  from: number;
  to: number;
  bucket_ms: number;
  max_points: number;
  series: Series[];
}

// --- Quản trị -----------------------------------------------------------------------------------

export interface RtuParams {
  port: string;
  baudrate: number;
  parity: 'N' | 'E' | 'O';
  stopbits: 1 | 2;
  timeout_ms: number;
  retries: number;
  gap_ms: number;
}

export interface TcpParams {
  host: string;
  port: number;
  framing: 'tcp' | 'rtu_over_tcp';
  timeout_ms: number;
  retries: number;
  gap_ms: number;
}

/** Tham số kết nối như server trả về: RTU có port là đường dẫn cổng serial, TCP có port là số. */
export interface ConnParams {
  port: string | number;
  baudrate?: number;
  parity?: 'N' | 'E' | 'O';
  stopbits?: 1 | 2;
  host?: string;
  framing?: 'tcp' | 'rtu_over_tcp';
  timeout_ms: number;
  retries: number;
  gap_ms: number;
}

export interface Connection {
  id: number;
  name: string;
  type: 'rtu' | 'tcp';
  params: ConnParams;
  enabled: boolean;
  created_at: number;
  updated_at: number;
  devices?: {
    id: number;
    name: string;
    unit_id: number;
    enabled: number;
    state: string | null;
    last_rtt_ms: number | null;
    last_ok_ts: number | null;
  }[];
  worker?: WorkerInfo | { state: 'stopped' } | null;
}

export interface SerialPort {
  path: string;
  device: string;
  stable: boolean;
  manufacturer: string | null;
  product: string | null;
  serial_number: string | null;
}

export interface ChannelDef {
  key: string;
  label: string;
  unit: string;
  fc: 3 | 4;
  address: number;
  type: 'int16' | 'uint16' | 'int32' | 'uint32' | 'float32';
  byte_order: 'ABCD' | 'CDAB' | 'BADC' | 'DCBA' | null;
  scale: number;
  offset: number;
  min: number | null;
  max: number | null;
  display_min: number | null;
  display_max: number | null;
  invalid_value: number | null;
  agg: 'mean' | 'circular_mean';
  decimals: number | null;
  estimate: boolean;
  note: string;
}

export interface Template {
  id: number;
  name: string;
  category: string;
  address_register: number | null;
  baud_register: number | null;
  baud_codes: Record<string, number> | null;
  channels: ChannelDef[];
  created_at: number;
  updated_at: number;
  devices: { id: number; name: string; zone: string }[];
}

export interface DeviceChannel {
  id: number;
  device_id: number;
  key: string;
  label: string;
  unit: string;
  display_min: number | null;
  display_max: number | null;
  alarm_low: number | null;
  alarm_high: number | null;
  enabled: boolean;
  value: number | null;
  ts: number | null;
  quality: string | null;
  template: {
    label: string;
    display_min: number | null;
    display_max: number | null;
    min: number | null;
    max: number | null;
    decimals: number;
    order: number;
  };
}

export interface AdminDevice {
  id: number;
  name: string;
  zone: string;
  connection_id: number;
  unit_id: number;
  template_id: number;
  poll_interval_s: number;
  enabled: boolean;
  template_name: string | null;
  connection_name: string | null;
  connection_type: 'rtu' | 'tcp' | null;
  state: string | null;
  since: number | null;
  last_ok_ts: number | null;
  last_rtt_ms: number | null;
  consecutive_failures: number | null;
  last_error: string | null;
  last_error_kind: string | null;
  last_error_ts: number | null;
  channels: DeviceChannel[];
}

export interface BusErrorInfo {
  kind: 'timeout' | 'crc' | 'exception' | 'io';
  message: string;
  code: number | null;
  name: string | null;
  fc: number | null;
  tx: string;
  rx: string;
  hint: string;
}

export interface TestReadResult {
  ok: boolean;
  at: number;
  rtt_ms?: number;
  requests: {
    fc: number;
    unit_id: number;
    address: number;
    count: number;
    tx: string;
    rx: string;
    rtt_ms: number;
    highlights: { key: string; start: number; len: number }[];
  }[];
  values: {
    key: string;
    label: string;
    unit: string;
    decimals: number;
    registers: string;
    raw_hex: string;
    raw: number | null;
    value: number | null;
    quality: string;
    detail: string | null;
  }[];
  error?: BusErrorInfo;
}

export interface User {
  id: number;
  username: string;
  role: 'admin' | 'viewer';
  is_active: boolean;
  must_change_password: boolean;
  created_at: number;
  last_login_at: number | null;
  is_me: boolean;
}

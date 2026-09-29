-- Migration 0001: lược đồ ban đầu theo spec mục 6.
-- Mọi thời điểm là epoch mili giây UTC. Không sửa file này sau khi phát hành; thay đổi thì thêm migration mới.

CREATE TABLE settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- Người dùng, phiên đăng nhập ------------------------------------------------------------

CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin', 'viewer')),
  is_active INTEGER NOT NULL DEFAULT 1,
  must_change_password INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  last_login_at INTEGER
);

CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf_token TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  last_seen_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  ip TEXT
);
CREATE INDEX sessions_user ON sessions(user_id);

CREATE TABLE login_failures (
  ip TEXT NOT NULL,
  username TEXT,
  ts INTEGER NOT NULL
);
CREATE INDEX login_failures_ip ON login_failures(ip, ts);

-- Cấu hình Modbus ------------------------------------------------------------------------

-- params là JSON, kiểm tra bằng Pydantic theo type (rtu: port, baudrate, parity...; tcp: host, port, framing...).
CREATE TABLE connections (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('rtu', 'tcp')),
  params TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

-- definition là JSON theo định dạng ở spec mục 4.4 (danh sách kênh, thanh ghi địa chỉ và baud rate).
CREATE TABLE device_templates (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  definition TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

-- Không đặt khóa ngoại cho connection_id, template_id: thiết bị đã xóa mềm vẫn giữ lịch sử và không được
-- chặn việc xóa kết nối hay mẫu. Web chỉ cho xóa khi không còn thiết bị (chưa xóa) nào dùng (409).
CREATE TABLE devices (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  zone TEXT NOT NULL DEFAULT '',
  connection_id INTEGER NOT NULL,
  unit_id INTEGER NOT NULL,
  template_id INTEGER NOT NULL,
  poll_interval_s INTEGER NOT NULL DEFAULT 10,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  deleted_at INTEGER
);
CREATE UNIQUE INDEX devices_unit_id ON devices(connection_id, unit_id) WHERE deleted_at IS NULL;

-- Sinh từ mẫu khi tạo thiết bị; id ổn định để gắn dữ liệu. display_min, display_max NULL thì dùng thang của mẫu.
CREATE TABLE channels (
  id INTEGER PRIMARY KEY,
  device_id INTEGER NOT NULL REFERENCES devices(id),
  key TEXT NOT NULL,
  label TEXT NOT NULL,
  unit TEXT NOT NULL DEFAULT '',
  display_min REAL,
  display_max REAL,
  alarm_low REAL,
  alarm_high REAL,
  enabled INTEGER NOT NULL DEFAULT 1,
  UNIQUE (device_id, key)
);

-- Dữ liệu đo -----------------------------------------------------------------------------

-- quality: 0 good, 1 out_of_range (vẫn lưu để điều tra, không gộp, không xét ngưỡng).
CREATE TABLE readings (
  channel_id INTEGER NOT NULL,
  ts INTEGER NOT NULL,
  value REAL NOT NULL,
  quality INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (channel_id, ts)
) WITHOUT ROWID;

-- Gộp 5 phút từ giá trị good, giữ vĩnh viễn. sin_avg, cos_avg chỉ dùng cho kênh circular_mean.
CREATE TABLE readings_5m (
  channel_id INTEGER NOT NULL,
  ts INTEGER NOT NULL,
  avg REAL NOT NULL,
  min REAL NOT NULL,
  max REAL NOT NULL,
  count INTEGER NOT NULL,
  sin_avg REAL,
  cos_avg REAL,
  PRIMARY KEY (channel_id, ts)
) WITHOUT ROWID;

-- Nguồn cho màn hình realtime. quality: good | out_of_range | sensor_fault.
CREATE TABLE channel_latest (
  channel_id INTEGER PRIMARY KEY,
  ts INTEGER NOT NULL,
  value REAL,
  quality TEXT NOT NULL,
  alarm TEXT,
  alarm_since INTEGER,
  fault_since INTEGER,
  detail TEXT
);

-- state: unknown | online | offline. counters là JSON: số request, timeout, CRC, exception, lỗi cảm biến, thời gian phản hồi.
CREATE TABLE device_status (
  device_id INTEGER PRIMARY KEY,
  state TEXT NOT NULL,
  since INTEGER,
  last_ok_ts INTEGER,
  last_error TEXT,
  last_error_kind TEXT,
  last_error_ts INTEGER,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  last_rtt_ms REAL,
  counters TEXT NOT NULL DEFAULT '{}',
  updated_at INTEGER
);

-- type: online | offline | sensor_fault | sensor_ok | error
CREATE TABLE device_events (
  id INTEGER PRIMARY KEY,
  device_id INTEGER NOT NULL,
  ts INTEGER NOT NULL,
  type TEXT NOT NULL,
  detail TEXT
);
CREATE INDEX device_events_device ON device_events(device_id, ts);

-- Bộ đếm theo cửa sổ 5 phút, cho tỷ lệ lỗi 1 giờ và 24 giờ trên trang Chẩn đoán (giữ 8 ngày).
CREATE TABLE device_stats_5m (
  device_id INTEGER NOT NULL,
  ts INTEGER NOT NULL,
  requests INTEGER NOT NULL DEFAULT 0,
  ok INTEGER NOT NULL DEFAULT 0,
  timeout INTEGER NOT NULL DEFAULT 0,
  crc INTEGER NOT NULL DEFAULT 0,
  exception INTEGER NOT NULL DEFAULT 0,
  sensor INTEGER NOT NULL DEFAULT 0,
  io INTEGER NOT NULL DEFAULT 0,
  rtt_sum REAL NOT NULL DEFAULT 0,
  rtt_n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (device_id, ts)
) WITHOUT ROWID;

CREATE TABLE frame_log (
  id INTEGER PRIMARY KEY,
  connection_id INTEGER NOT NULL,
  ts INTEGER NOT NULL,
  dir TEXT NOT NULL,
  hex TEXT NOT NULL,
  note TEXT
);
CREATE INDEX frame_log_connection ON frame_log(connection_id, id);

-- Nhật ký thay đổi: before, after là JSON; summary là câu mô tả tiếng Việt cho người đọc.
CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY,
  ts INTEGER NOT NULL,
  user_id INTEGER,
  username TEXT,
  action TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id INTEGER,
  before TEXT,
  after TEXT,
  summary TEXT
);
CREATE INDEX audit_log_ts ON audit_log(ts);

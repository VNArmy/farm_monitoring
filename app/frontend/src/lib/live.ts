// Dữ liệu trực tiếp qua SSE (spec mục 7): snapshot khi mới nối, sau đó chỉ phần thay đổi
// (reading, device_status, system; riêng HMI thêm hmi_config, reload). Kèm đường xu hướng 1 giờ.
import { computed, inject, reactive, type ComputedRef, type InjectionKey } from 'vue';
import { api } from './api';
import { setTimezone } from './format';
import type { Channel, Derived, Device, HmiConfig, Metric, Snapshot, Spark } from './types';

const SPARK_REFRESH_MS = 60_000;
const SPARK_WINDOW_MS = 3_600_000;

export interface LiveOptions {
  overviewUrl: string;
  streamUrl: () => string;
  sparkUrl: string;
  /** Lỗi kết nối kéo dài quá lâu thì báo mất kết nối. */
  lostAfterMs?: number;
  /** Không nhận sự kiện nào (kể cả ping 15 giây) quá lâu thì báo mất kết nối. HMI: 30 giây. */
  silenceMs?: number;
  onHmiConfig?: (cfg: HmiConfig) => void;
  onReload?: () => void;
  onVersion?: (version: string) => void;
}

export interface LiveState {
  snap: Snapshot | null;
  connected: boolean;
  errorAt: number | null;
  lastEventAt: number;
  now: number;
  sparks: Record<string, Spark>;
}

export interface Live {
  state: LiveState;
  lost: ComputedRef<boolean>;
  start: () => void;
  channel: (id: number | string) => Metric | null;
  spark: (m: Metric) => Spark | null;
  latestTs: ComputedRef<number | null>;
}

export const LIVE: InjectionKey<Live> = Symbol('live');

export function useLive(): Live {
  const live = inject(LIVE);
  if (!live) throw new Error('Chưa có luồng trực tiếp');
  return live;
}

export function vpd(t: number, rh: number): number {
  const svp = 0.6108 * Math.exp((17.27 * t) / (t + 237.3));
  return svp * (1 - rh / 100);
}

export function createLive(opts: LiveOptions): Live {
  const state = reactive<LiveState>({
    snap: null,
    connected: false,
    errorAt: null,
    lastEventAt: 0,
    now: Date.now(),
    sparks: {},
  });
  let es: EventSource | null = null;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let started = false;

  const mark = (): void => {
    state.connected = true;
    state.errorAt = null;
    state.lastEventAt = Date.now();
  };

  function setSnap(s: Snapshot): void {
    state.snap = s;
    setTimezone(s.timezone);
    opts.onVersion?.(s.frontend_version);
    for (const c of s.channels) appendSpark(c);
  }

  function appendSpark(m: Metric): void {
    if (typeof m.id !== 'number') return;
    const s = state.sparks[String(m.id)];
    if (!s || m.value == null || m.ts == null || !['ok', 'alarm'].includes(m.state)) return;
    const last = s.points[s.points.length - 1];
    if (last && m.ts <= last[0] + 5000) return;
    s.points.push([m.ts, m.value]);
    const from = Date.now() - SPARK_WINDOW_MS;
    while (s.points.length && s.points[0][0] < from) s.points.shift();
    s.min = s.min == null ? m.value : Math.min(s.min, m.value);
    s.max = s.max == null ? m.value : Math.max(s.max, m.value);
  }

  function upsert<T extends { id: number | string }>(list: T[], item: T): void {
    const i = list.findIndex((x) => x.id === item.id);
    if (i >= 0) list[i] = item;
    else list.push(item);
  }

  async function loadSparks(): Promise<void> {
    try {
      const r = await api.get<{ channels: Record<string, Spark> }>(opts.sparkUrl);
      state.sparks = r.channels;
    } catch {
      // lần sau thử lại
    }
  }

  async function reloadSnapshot(): Promise<void> {
    try {
      setSnap(await api.get<Snapshot>(opts.overviewUrl));
    } catch {
      // luồng trực tiếp sẽ thử lại
    }
  }

  function connect(): void {
    clearTimeout(retry);
    es?.close();
    const src = new EventSource(opts.streamUrl());
    es = src;
    const on = (name: string, fn: (data: never) => void): void =>
      src.addEventListener(name, (e) => {
        mark();
        fn(JSON.parse((e as MessageEvent<string>).data) as never);
      });
    src.onopen = mark;
    on('snapshot', (s: Snapshot) => setSnap(s));
    on('reading', (m: Channel | Derived) => {
      if (!state.snap) return;
      if (typeof m.id === 'string') upsert(state.snap.derived, m as Derived);
      else {
        upsert(state.snap.channels, m as Channel);
        appendSpark(m);
      }
    });
    on('device_status', (d: Device) => {
      if (state.snap) upsert(state.snap.devices, d);
    });
    on('system', (sys: Partial<Snapshot>) => {
      if (!state.snap) return;
      Object.assign(state.snap, sys);
      if (sys.timezone) setTimezone(sys.timezone);
      if (sys.frontend_version) opts.onVersion?.(sys.frontend_version);
    });
    on('hmi_config', (cfg: HmiConfig) => {
      if (state.snap) state.snap.hmi = cfg;
      opts.onHmiConfig?.(cfg);
    });
    on('reload', () => opts.onReload?.());
    on('ping', () => undefined);
    src.onerror = () => {
      state.connected = false;
      if (state.errorAt == null) state.errorAt = Date.now();
      if (src.readyState === EventSource.CLOSED) {
        // Server trả lỗi (ví dụ hết phiên): hỏi lại ảnh chụp để biết lý do, rồi nối lại.
        es = null;
        retry = setTimeout(async () => {
          await reloadSnapshot();
          connect();
        }, 3000);
      }
    };
  }

  const lost = computed(() => {
    const now = state.now;
    if (state.errorAt != null && now - state.errorAt > (opts.lostAfterMs ?? 4000)) return true;
    return state.lastEventAt > 0 && now - state.lastEventAt > (opts.silenceMs ?? 35_000);
  });

  const latestTs = computed(() => {
    let m = 0;
    for (const c of state.snap?.channels ?? []) if (c.ts && c.ts > m) m = c.ts;
    return m || null;
  });

  function channel(id: number | string): Metric | null {
    const s = state.snap;
    if (!s) return null;
    return typeof id === 'string' ? (s.derived.find((d) => d.id === id) ?? null) : (s.channels.find((c) => c.id === id) ?? null);
  }

  /** Xu hướng 1 giờ; VPD tính từ nhiệt độ và độ ẩm cùng mốc thời gian. */
  function spark(m: Metric): Spark | null {
    if (typeof m.id === 'number') return state.sparks[String(m.id)] ?? null;
    const d = m as Derived;
    const t = state.sparks[String(d.inputs?.[0])];
    const h = state.sparks[String(d.inputs?.[1])];
    if (!t || !h) return null;
    const hm = new Map(h.points.map((p) => [p[0], p[1]]));
    const points: [number, number][] = [];
    for (const [ts, tv] of t.points) {
      const hv = hm.get(ts);
      if (hv != null) points.push([ts, vpd(tv, hv)]);
    }
    const vals = points.map((p) => p[1]);
    return { points, min: vals.length ? Math.min(...vals) : null, max: vals.length ? Math.max(...vals) : null };
  }

  async function start(): Promise<void> {
    if (started) return;
    started = true;
    // Rời trang thì đóng luồng: trang nằm trong back-forward cache vẫn giữ kết nối SSE, mà trình duyệt chỉ cho
    // 6 kết nối HTTP/1.1 mỗi host, nên vài lần tải lại là request mới bị treo.
    window.addEventListener('pagehide', () => {
      clearTimeout(retry);
      es?.close();
      es = null;
    });
    window.addEventListener('pageshow', (e) => {
      if (!e.persisted) return;
      void reloadSnapshot();
      connect();
    });
    await Promise.all([reloadSnapshot(), loadSparks()]);
    connect();
    setInterval(() => (state.now = Date.now()), 1000);
    setInterval(loadSparks, SPARK_REFRESH_MS);
  }

  return { state, lost, start: () => void start(), channel, spark, latestTs };
}

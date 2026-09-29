// Biểu tượng nét (stroke) lấy từ bản thiết kế; vẽ bằng component Icon.

export const ICONS: Record<string, string> = {
  logo: '<path d="M3 11l9-7l9 7"/><path d="M5 10v10h14v-10"/><path d="M12 20v-5"/><path d="M12 15c0-2 1.5-3.5 3.5-3.5c0 2-1.5 3.5-3.5 3.5z"/>',
  grid: '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/>',
  chart: '<path d="M4 19h16"/><path d="M4 15l4-6l4 2l4-5l4 4"/>',
  plug: '<path d="M9.79 6l8.21 8.21l-2.05 2.06a5.81 5.81 0 1 1-8.22-8.22l2.06-2.05z"/><path d="M4 20l3.5-3.5"/><path d="M15 4l-3.5 3.5"/><path d="M20 9l-3.5 3.5"/>',
  plugOff: '<path d="M16.12 16.09l-.17.18a5.81 5.81 0 1 1-8.22-8.22l.16-.16"/><path d="M4 20l3.5-3.5"/><path d="M15 4l-3.5 3.5"/><path d="M20 9l-3.5 3.5"/><path d="M3 3l18 18"/>',
  table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18"/><path d="M10 4v16"/>',
  chip: '<rect x="5" y="5" width="14" height="14" rx="1"/><path d="M9 9h6v6h-6z"/><path d="M3 10h2M3 14h2M10 3v2M14 3v2M21 10h-2M21 14h-2M14 21v-2M10 21v-2"/>',
  scan: '<path d="M4 7v-2a1 1 0 0 1 1-1h2"/><path d="M4 17v2a1 1 0 0 0 1 1h2"/><path d="M16 4h2a1 1 0 0 1 1 1v2"/><path d="M16 20h2a1 1 0 0 0 1-1v-2"/><path d="M5 12h14"/>',
  pulse: '<path d="M3 12h4l3 8l4-16l3 8h4"/>',
  users: '<circle cx="9" cy="7" r="4"/><path d="M3 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/><path d="M21 21v-2a4 4 0 0 0-3-3.85"/>',
  sliders: '<path d="M4 6h8M16 6h4M4 12h2M10 12h10M4 18h11M19 18h1"/><circle cx="14" cy="6" r="2"/><circle cx="8" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
  collapse: '<path d="M11 7l-5 5l5 5"/><path d="M17 7l-5 5l5 5"/>',
  logout: '<path d="M14 8v-2a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2v-2"/><path d="M9 12h12l-3-3"/><path d="M18 15l3-3"/>',
  eye: '<path d="M10 12a2 2 0 1 0 4 0a2 2 0 0 0-4 0"/><path d="M21 12c-2.4 4-5.4 6-9 6c-3.6 0-6.6-2-9-6c2.4-4 5.4-6 9-6c3.6 0 6.6 2 9 6"/>',
  eyeOff: '<path d="M10.585 10.587a2 2 0 0 0 2.829 2.828"/><path d="M16.681 16.673a8.717 8.717 0 0 1-4.681 1.327c-3.6 0-6.6-2-9-6c1.272-2.12 2.712-3.678 4.32-4.674m2.86-1.146a9.055 9.055 0 0 1 1.82-.18c3.6 0 6.6 2 9 6c-.666 1.11-1.379 2.067-2.138 2.87"/><path d="M3 3l18 18"/>',
  qr: '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><path d="M14 14h3v3h-3z"/><path d="M20 14v.01"/><path d="M14 20h.01"/><path d="M17 20h3v-3"/>',
  warn: '<path d="M12 9v4"/><path d="M10.36 3.59l-8.1 13.53a1.91 1.91 0 0 0 1.63 2.88h16.22a1.91 1.91 0 0 0 1.63-2.88l-8.1-13.53a1.91 1.91 0 0 0-3.28 0z"/><path d="M12 16h.01"/>',
  xCircle: '<circle cx="12" cy="12" r="9"/><path d="M10 10l4 4m0-4l-4 4"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="M9 12l2 2l4-4"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 8h.01"/><path d="M11 12h1v4h1"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/>',
  thermo: '<path d="M10 13.5a4 4 0 1 0 4 0v-8.5a2 2 0 0 0-4 0v8.5"/><path d="M10 9h4"/>',
  drop: '<path d="M7.5 19.42c2.6 2.1 6.4 2.1 9 0c2.6-2.1 3.26-5.71 1.57-8.55l-4.89-7.26a1.38 1.38 0 0 0-2.35 0l-4.9 7.26c-1.69 2.84-1.03 6.44 1.57 8.55z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M3 12h1m8-9v1m8 8h1m-9 8v1M5.6 5.6l.7.7m12.1-.7l-.7.7m0 11.4l.7.7m-12.1-.7l-.7.7"/>',
  cloud: '<path d="M6.657 18c-2.572 0-4.657-2.007-4.657-4.483c0-2.475 2.085-4.482 4.657-4.482c.393-1.762 1.794-3.2 3.675-3.773c1.88-.572 3.956-.193 5.444 1c1.488 1.19 2.162 3.007 1.77 4.769h.99c1.913 0 3.464 1.56 3.464 3.486c0 1.927-1.551 3.487-3.465 3.487h-11.878"/>',
  wind: '<path d="M5 8h8.5a2.5 2.5 0 1 0-2.34-3.24"/><path d="M3 12h15.5a2.5 2.5 0 1 1-2.34 3.24"/><path d="M4 16h5.5a2.5 2.5 0 1 1-2.34 3.24"/>',
  gauge: '<path d="M12 13m-8 0a8 8 0 1 0 16 0a8 8 0 1 0-16 0"/><path d="M12 13l3.5-3.5"/><path d="M7 13h.01M17 13h.01M12 8h.01"/>',
  leaf: '<path d="M5 21c.5-4.5 2.5-8 7-10"/><path d="M9 18c6.218 0 10.5-3.288 11-12v-2h-4.014c-9 0-11.986 4-12 9c0 1 0 3 2 5h3z"/>',
  plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
  x: '<path d="M18 6l-12 12"/><path d="M6 6l12 12"/>',
  download: '<path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/><path d="M7 11l5 5l5-5"/><path d="M12 4v12"/>',
  upload: '<path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/><path d="M7 9l5-5l5 5"/><path d="M12 4v12"/>',
  refresh: '<path d="M20 11a8.1 8.1 0 0 0-15.5-2m-.5-4v4h4"/><path d="M4 13a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4"/>',
  play: '<path d="M7 4v16l13-8z"/>',
  stop: '<rect x="5" y="5" width="14" height="14" rx="2"/>',
  pause: '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8v-2a2 2 0 0 0-2-2h-8a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  down: '<path d="M6 9l6 6l6-6"/>',
  up: '<path d="M6 15l6-6l6 6"/>',
  right: '<path d="M9 6l6 6l-6 6"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="M10.85 12.15l8.15-8.15"/><path d="M18 5l2 2"/><path d="M15 8l2 2"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11v-4a4 4 0 1 1 8 0v4"/>',
  user: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="10" r="3"/><path d="M6.17 18.85a4 4 0 0 1 3.83-2.85h4a4 4 0 0 1 3.83 2.86"/>',
  shrink: '<path d="M7 7l5 5l5-5"/><path d="M7 13l5 5l5-5"/>',
  expand: '<path d="M7 11l5-5l5 5"/><path d="M7 17l5-5l5 5"/>',
  menu: '<path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/>',
  trash: '<path d="M4 7h16"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-12"/><path d="M9 7v-3a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3"/>',
  save: '<path d="M6 4h10l4 4v10a2 2 0 0 1-2 2h-12a2 2 0 0 1-2-2v-12a2 2 0 0 1 2-2"/><path d="M12 14m-2 0a2 2 0 1 0 4 0a2 2 0 1 0-4 0"/><path d="M14 4v4h-6v-4"/>',
  arrowUp: '<path d="M12 5v14"/><path d="M18 11l-6-6"/><path d="M6 11l6-6"/>',
  arrowDown: '<path d="M12 5v14"/><path d="M18 13l-6 6"/><path d="M6 13l6 6"/>',
  edit: '<path d="M4 20h4l10.5-10.5a2.83 2.83 0 1 0-4-4l-10.5 10.5v4"/><path d="M13.5 6.5l4 4"/>',
  wifi: '<path d="M12 18h.01"/><path d="M9.17 15.17a4 4 0 0 1 5.66 0"/><path d="M6.34 12.34a8 8 0 0 1 11.31 0"/><path d="M3.52 9.52a12 12 0 0 1 16.97 0"/>',
  terminal: '<path d="M5 7l5 5l-5 5"/><path d="M12 19h7"/>',
};

export const GRIP = '<circle cx="9" cy="6" r="1.5"/><circle cx="15" cy="6" r="1.5"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/><circle cx="9" cy="18" r="1.5"/><circle cx="15" cy="18" r="1.5"/>';

/** Biểu tượng theo key kênh: temperature, humidity, illuminance, co2, wind_speed, vpd. */
export function channelIcon(key = '', unit = ''): string {
  const k = key.toLowerCase();
  if (k.includes('temp') || unit === '°C') return 'thermo';
  if (k.includes('hum') || k === 'rh' || unit === '%RH') return 'drop';
  if (k.includes('lux') || k.includes('illum') || k.includes('light') || unit === 'lux') return 'sun';
  if (k.includes('co2') || unit === 'ppm') return 'cloud';
  if (k.includes('wind')) return 'wind';
  if (k.includes('vpd')) return 'leaf';
  return 'gauge';
}

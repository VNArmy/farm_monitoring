// Mục điều hướng của web app.

export interface NavItem {
  id: string;
  to: string;
  label: string;
  icon: string;
}

export const MAIN_NAV: NavItem[] = [
  { id: 'tong-quan', to: '/', label: 'Tổng quan', icon: 'grid' },
  { id: 'bieu-do', to: '/bieu-do', label: 'Biểu đồ', icon: 'chart' },
];

export const ADMIN_NAV: NavItem[] = [
  { id: 'ket-noi', to: '/quan-tri/ket-noi', label: 'Kết nối', icon: 'plug' },
  { id: 'mau', to: '/quan-tri/mau', label: 'Mẫu thiết bị', icon: 'table' },
  { id: 'thiet-bi', to: '/quan-tri/thiet-bi', label: 'Thiết bị', icon: 'chip' },
  { id: 'quet', to: '/quan-tri/quet', label: 'Quét bus', icon: 'scan' },
  { id: 'chan-doan', to: '/quan-tri/chan-doan', label: 'Chẩn đoán', icon: 'pulse' },
  { id: 'nguoi-dung', to: '/quan-tri/nguoi-dung', label: 'Người dùng', icon: 'users' },
  { id: 'cai-dat', to: '/quan-tri/cai-dat', label: 'Cài đặt', icon: 'sliders' },
];

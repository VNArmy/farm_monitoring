import { resolve } from 'node:path';
import vue from '@vitejs/plugin-vue';
import { defineConfig } from 'vite';

// Hai entry: web app (index.html) và màn hình HMI (hmi.html) để Chromium trên Pi tải ít mã hơn.
// Khi phát triển: `greenhouse dev` chạy web ở 8080 và HMI ở 8081; Vite chuyển tiếp /api tới đó.
// Mở http://localhost:5173/ cho web app, http://localhost:5173/hmi.html cho HMI.
export default defineConfig({
  plugins: [vue()],
  build: {
    target: 'es2020',
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: resolve(__dirname, 'index.html'),
        hmi: resolve(__dirname, 'hmi.html'),
      },
    },
  },
  server: {
    proxy: {
      '/api/hmi': { target: 'http://127.0.0.1:8081', changeOrigin: false },
      '/api': { target: 'http://127.0.0.1:8080', changeOrigin: false },
    },
  },
  test: {
    include: ['src/**/*.test.ts'],
  },
});

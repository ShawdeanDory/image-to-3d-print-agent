import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 同源代理，浏览器不持有云端密钥，不需要开放AutoDL公网端口。
export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true,
    proxy: { '/api': { target: process.env.I3D_API_TARGET || 'http://127.0.0.1:8000', changeOrigin: false } } },
  preview: { host: '127.0.0.1', port: 5173, strictPort: true,
    proxy: { '/api': { target: process.env.I3D_API_TARGET || 'http://127.0.0.1:8000', changeOrigin: false } } },
});

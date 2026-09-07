import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期代理到 FastAPI（同源 Cookie，免 CORS）。
// 默认 8100（本机 8000 落在 Windows Hyper-V 保留端口段，起不来）；可用 VITE_API_TARGET 覆盖。
const target = process.env.VITE_API_TARGET || 'http://127.0.0.1:8100'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target, changeOrigin: true },
      '/mcp': { target, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500,
  },
})

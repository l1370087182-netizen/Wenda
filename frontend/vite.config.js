import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期代理到 FastAPI（同源 Cookie，免 CORS）；生产构建产物由后端同源托管
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8100',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500,
  },
})

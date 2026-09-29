import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 走代理，前端用相对路径即可，且 EventSource 不需要处理跨域
    proxy: {
      '/api': 'http://127.0.0.1:8010',
    },
  },
})

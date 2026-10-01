import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// API 代理目标可用 VITE_API_TARGET 覆盖：一台机器同时跑两套实例
// （例如对比新旧版本、或 8010 被别的进程占着）时不必改仓库文件。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 走代理，前端用相对路径即可，且 EventSource 不需要处理跨域
    proxy: {
      // ws: true —— 流式转写走 /api/asr/stream WebSocket，dev server 必须放行升级
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8010',
        ws: true,
      },
    },
  },
})

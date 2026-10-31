import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// API 代理目标可用 VITE_API_TARGET 覆盖：一台机器同时跑两套实例
// （例如对比新旧版本、或 8010 被别的进程占着）时不必改仓库文件。
export default defineConfig({
  plugins: [
    react(),
    // PWA 离线壳：precache 全部静态资源（本地模型模式下断网场馆也能加载界面）；
    // API 一律不缓存（分析/对练必须实时）。autoUpdate：发新版本自动换壳。
    // dev 模式不启用（HMR 不受影响）。manifest 沿用 public/manifest.webmanifest。
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      // manifest 沿用 public/manifest.webmanifest 手写版（含中文名称与图标）——
      // 插件默认生成的 manifest（英文名、零图标、Vue 绿主题）会在构建时覆盖它
      manifest: false,
      includeAssets: ['icon-192.png', 'icon-512.png'],
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        navigateFallback: 'index.html',
      },
    }),
  ],
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

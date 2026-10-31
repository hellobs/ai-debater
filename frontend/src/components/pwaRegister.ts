/** SW 注册（生产构建才有 sw.js；vite dev 不注入所以此处自然跳过）。
 *  autoUpdate 模式：新版本下载完成后下次加载生效，不打断正在进行的比赛。
 *  manifest 沿用 public/manifest.webmanifest 手写版（vite.config 里 manifest: false，
 *  否则插件的默认 manifest 会在构建时覆盖手写版——2026-10-31 体检实测）。 */
export function registerPWA(): void {
  if (!('serviceWorker' in navigator)) return
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js').catch(() => { /* 注册失败静默：离线能力是增强项 */ })
  })
}

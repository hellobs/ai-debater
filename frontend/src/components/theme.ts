/** 外观三态：跟随系统 / 浅色 / 深色。
 *  CSS 侧的接口在 styles.css：系统偏好走 `:root:not(.light)`（media query），
 *  手动深色走 `html.dark`，手动浅色走 `html.light`（压制系统深色）。
 *  本模块只负责往 html 上挂/摘这两个类，并持久化选择。 */

export type ThemeMode = 'auto' | 'light' | 'dark'

const THEME_KEY = 'debater.theme'

export function loadThemeMode(): ThemeMode {
  try {
    const v = localStorage.getItem(THEME_KEY)
    return v === 'light' || v === 'dark' ? v : 'auto'
  } catch {
    return 'auto'
  }
}

export function saveThemeMode(mode: ThemeMode): void {
  try { localStorage.setItem(THEME_KEY, mode) } catch { /* 隐私模式忽略 */ }
  applyThemeMode(mode)
}

/** 往 html 挂/摘类。auto = 清掉两个类（交给系统偏好）。 */
export function applyThemeMode(mode: ThemeMode): void {
  const el = document.documentElement
  el.classList.toggle('dark', mode === 'dark')
  el.classList.toggle('light', mode === 'light')
}

/** auto 模式下系统深浅切换时实时跟随（matchMedia 监听由调用方挂一次）。 */
export function watchSystemTheme(): void {
  try {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', () => {
      if (loadThemeMode() === 'auto') applyThemeMode('auto')
    })
  } catch { /* 忽略 */ }
}

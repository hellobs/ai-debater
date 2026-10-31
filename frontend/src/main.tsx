import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { registerPWA } from './components/pwaRegister'
import { applyThemeMode, loadThemeMode, watchSystemTheme } from './components/theme'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

registerPWA()

// 外观：启动即应用持久化的三态（auto/light/dark），auto 下系统切换实时跟随
applyThemeMode(loadThemeMode())
watchSystemTheme()

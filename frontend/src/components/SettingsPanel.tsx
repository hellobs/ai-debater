import { useEffect, useState } from 'react'
import { fetchHealth } from '../api'
import type { HealthInfo } from '../types'

const SIDE_PRESETS = [
  '控方（主张应享有）',
  '辩方（主张不应享有）',
  '正方',
  '反方',
]

export default function SettingsPanel(props: {
  topic: string
  ourSide: string
  opponentText: string
  running: boolean
  sessionId: string | null
  onTopic: (v: string) => void
  onSide: (v: string) => void
  onOpponent: (v: string) => void
  onSubmit: () => void
  onReset: () => void
}) {
  const {
    topic, ourSide, opponentText, running, sessionId,
    onTopic, onSide, onOpponent, onSubmit, onReset,
  } = props

  const [health, setHealth] = useState<HealthInfo | null>(null)
  const [healthErr, setHealthErr] = useState<string | null>(null)

  const check = async () => {
    setHealthErr(null)
    try {
      setHealth(await fetchHealth())
    } catch (e) {
      setHealth(null)
      setHealthErr(String(e))
    }
  }

  useEffect(() => {
    void check()
  }, [])

  return (
    <aside className="panel">
      <h1 className="brand">法学辩论现场参谋台</h1>
      <p className="brand-sub">多 Agent 并行给你出主意，用不用由你判断</p>

      <label className="block">
        <span className="block-label">① 辩题</span>
        <input
          className="text-input"
          value={topic}
          onChange={(e) => onTopic(e.target.value)}
          placeholder="例：AI 生成内容是否应享有著作权"
        />
      </label>

      <label className="block">
        <span className="block-label">② 我方立场</span>
        <select
          className="text-input"
          value={ourSide}
          onChange={(e) => onSide(e.target.value)}
        >
          {SIDE_PRESETS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </label>

      <label className="block">
        <span className="block-label">③ 对方刚说的话</span>
        <textarea
          className="text-input"
          rows={6}
          value={opponentText}
          onChange={(e) => onOpponent(e.target.value)}
          placeholder="把对方刚才的发言打进来（ASR 语音转写已规划在后置阶段）"
        />
      </label>

      <div className="actions">
        <button
          className="btn-primary"
          disabled={running || !topic.trim() || !opponentText.trim()}
          onClick={onSubmit}
        >
          {running ? '并行分析中…' : '生成参谋建议'}
        </button>
        <button className="btn-ghost" onClick={onReset} disabled={running}>
          清空结果
        </button>
      </div>

      <div className="status">
        <div className="status-head">
          <span className="block-label">④ 服务状态</span>
          <button className="btn-mini" onClick={() => void check()}>重新检测</button>
        </div>
        {health ? (
          <ul className="status-list">
            <li><b>模型</b> {health.model}</li>
            <li>
              <b>上游凭据</b>{' '}
              <span className={health.upstream_configured ? 'ok-text' : 'err-text'}>
                {health.upstream_configured ? '已配置' : '未配置'}
              </span>
            </li>
            <li><b>协议桥</b> {health.bridge}</li>
            <li>
              <b>参谋团</b> {health.advisors.map((a) => a.label).join(' · ')}
            </li>
            <li>
              <b>会话</b> {sessionId ? <code>{sessionId}</code> : '提交后创建'}
            </li>
          </ul>
        ) : (
          <p className="error">
            后端未连通{healthErr ? `：${healthErr}` : ''}
            <br />
            <span className="muted">
              先在 backend 目录启动 <code>python -m app.main</code>，
              并确保协议桥在跑。
            </span>
          </p>
        )}
      </div>
    </aside>
  )
}

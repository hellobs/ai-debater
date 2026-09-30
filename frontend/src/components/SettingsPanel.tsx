import { useState } from 'react'
import { BUDGET_PRESETS, type HealthInfo, type Topic } from '../types'

/** 按 domain 分组，保持后端返回顺序（= 配置顺序）。 */
function groupByDomain(topics: Topic[]): [string, Topic[]][] {
  const groups: [string, Topic[]][] = []
  for (const t of topics) {
    const hit = groups.find(([d]) => d === t.domain)
    if (hit) hit[1].push(t)
    else groups.push([t.domain, [t]])
  }
  return groups
}

export default function SettingsPanel(props: {
  topic: string
  ourSide: string
  opponentText: string
  running: boolean
  sessionId: string | null
  budget: number
  health: HealthInfo | null
  healthErr: string | null
  onRecheck: () => Promise<void>
  topics: Topic[]
  selectedTopicId: string
  onSelectTopic: (id: string) => void
  onSaveTopic: () => void
  onDeleteTopic: () => void
  saving: boolean
  /** 辩题库操作的回执（保存/删除），只在左侧面板就近显示 */
  topicMsg: string
  onTopic: (v: string) => void
  onSide: (v: string) => void
  onOpponent: (v: string) => void
  onBudget: (v: number) => void
  onSubmit: () => void
  onReset: () => void
}) {
  const {
    topic, ourSide, opponentText, running, sessionId, budget,
    health, healthErr, onRecheck,
    topics, selectedTopicId, onSelectTopic, onSaveTopic, onDeleteTopic, saving,
    topicMsg,
    onTopic, onSide, onOpponent, onBudget, onSubmit, onReset,
  } = props

  const [checking, setChecking] = useState(false)

  /** 健康状态归父级一份（App 还要用它渲染参谋列），这里只负责触发与按钮态。 */
  const check = async () => {
    setChecking(true)
    try {
      await onRecheck()
    } finally {
      setChecking(false)
    }
  }

  const selected = topics.find((t) => t.id === selectedTopicId) ?? null
  const groups = groupByDomain(topics)

  // 立场选项由辩题带出；若当前值不在其中（自定义过），额外补一项，避免下拉吞掉它
  const sideOptions = selected ? [selected.side_a, selected.side_b] : ['正方', '反方']
  const sides = ourSide && !sideOptions.includes(ourSide)
    ? [...sideOptions, ourSide]
    : sideOptions

  return (
    <aside className="panel">
      <h1 className="brand">{health?.brand ?? '辩手参谋台'}</h1>
      <p className="brand-sub">多 Agent 并行给你出主意，用不用由你判断</p>

      <label className="block">
        <span className="block-label">① 辩题</span>
        <select
          className="text-input"
          value={selectedTopicId}
          onChange={(e) => onSelectTopic(e.target.value)}
        >
          <option value="">— 自定义辩题（在下面直接写）—</option>
          {groups.map(([domain, items]) => (
            <optgroup key={domain} label={domain}>
              {items.map((t) => (
                <option key={t.id} value={t.id}>{t.title}</option>
              ))}
            </optgroup>
          ))}
        </select>
        <input
          className="text-input spaced"
          value={topic}
          onChange={(e) => onTopic(e.target.value)}
          placeholder="例：AI 生成内容是否应享有著作权"
        />
        <span className="row-actions">
          <button
            className="btn-inline"
            onClick={onSaveTopic}
            disabled={saving || !topic.trim()}
            title="把当前辩题、我方立场与对方例句一起存进 data/topics.json（不入仓）"
          >
            保存为我的辩题
          </button>
          {selected?.source === 'local' && (
            <button
              className="btn-inline danger"
              onClick={onDeleteTopic}
              disabled={saving}
              title="只删得掉本机自建的那份，入仓预设删不动"
            >
              删除
            </button>
          )}
        </span>
        <span className="hint">
          {selected?.note
            ? `争点：${selected.note}`
            : '辩题库来自 configs/topics.yaml（入仓预设）与 data/topics.json（本机自建）。选定辩题会自动带出立场。'}
        </span>
        {topicMsg && <span className="topic-msg">{topicMsg}</span>}
      </label>

      <label className="block">
        <span className="block-label">② 我方立场</span>
        <select
          className="text-input"
          value={ourSide}
          onChange={(e) => onSide(e.target.value)}
        >
          {sides.map((s) => (
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

      <label className="block">
        <span className="block-label">④ 时间预算（现场调这个）</span>
        <select
          className="text-input"
          value={budget}
          onChange={(e) => onBudget(Number(e.target.value))}
        >
          {BUDGET_PRESETS.map((b) => (
            <option key={b.value} value={b.value}>{b.label}</option>
          ))}
        </select>
        <span className="hint">
          到点仍未返回的参谋会被标为「超时」并立刻交付，不阻塞已好的结果。
        </span>
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
          <span className="block-label">⑤ 服务状态</span>
          <button className="btn-mini" onClick={() => void check()} disabled={checking}>
            {checking ? '检测中…' : '重新检测'}
          </button>
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
              <b>参谋团</b>{' '}
              {health.advisors.length === 0
                ? '（未启用任何一路）'
                : health.advisors.map((a, i) => (
                    <span key={a.name}>
                      {i > 0 && ' · '}
                      {a.label}
                      {a.domain && <span className="roster-tag">{a.domain}</span>}
                    </span>
                  ))}
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

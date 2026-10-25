/** 备赛模式容器：四个板块的子导航与切换。 */
import { useState } from 'react'
import { ARENA_QUESTIONS } from './engine'
import { DraftView } from './DraftView'
import { LibraryView } from './LibraryView'
import { SplitView } from './SplitView'

const TABS = [
  { k: 'split', label: '拆题台' },
  { k: 'draft', label: '稿件生成' },
  { k: 'arena', label: '攻防演练' },
  { k: 'library', label: '素材库' },
] as const
type TabKey = (typeof TABS)[number]['k']

export default function PrepView() {
  const [tab, setTab] = useState<TabKey>('split')
  return (
    <div className="prep">
      <div className="prep-nav">
        {TABS.map((t) => (
          <button key={t.k} className={tab === t.k ? 'on' : ''} onClick={() => setTab(t.k)}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'split' && <SplitView />}
      {tab === 'draft' && <DraftView />}
      {tab === 'arena' && <ArenaView />}
      {tab === 'library' && <LibraryView />}
    </div>
  )
}

const TYPE_LABEL: Record<string, string> = {
  def: '定义战', std: '判准战', logic: '归谬逻辑',
  example: '例证攻防', value: '价值升维',
}

/** 攻防演练：抽题 → 自己想 15 秒 → 看应对要点 → 自评。记录只留本轮内存。 */
function ArenaView() {
  const [idx, setIdx] = useState(0)
  const [showTip, setShowTip] = useState(false)
  const [log, setLog] = useState<string[]>([])
  const q = ARENA_QUESTIONS[idx % ARENA_QUESTIONS.length]
  const rate = (verdict: string) =>
    setLog((l) => [...l, `「${q.src}」${TYPE_LABEL[q.t] ?? q.t} → ${verdict}`])

  return (
    <div>
      <div className="prep-card">
        <div className="arena-meta">{q.src} · {TYPE_LABEL[q.t] ?? q.t} · 第 {idx + 1} / {ARENA_QUESTIONS.length} 题</div>
        <div className="arena-q">{q.q}</div>
        <div className="prep-actions">
          <button className="btn-mini" onClick={() => { setIdx((i) => (i + 1) % ARENA_QUESTIONS.length); setShowTip(false) }}>
            下一题 ▸
          </button>
          <button className="btn-mini" onClick={() => setShowTip((v) => !v)}>
            {showTip ? '收起要点' : '看应对要点'}
          </button>
        </div>
        {showTip && <div className="arena-tip">{q.tip}</div>}
        {showTip && (
          <div className="prep-actions" title="诚实自评：演练的价值在记录">
            <span className="muted">自评：</span>
            {['妙极', '稳住', '险胜', '被打穿'].map((v) => (
              <button key={v} className="btn-mini" onClick={() => rate(v)}>{v}</button>
            ))}
          </div>
        )}
        {log.length > 0 && (
          <ul className="prep-log">{log.map((x, i) => <li key={i}>{x}</li>)}</ul>
        )}
      </div>
    </div>
  )
}

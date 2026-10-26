/** 备赛模式容器：四个板块的子导航与切换。 */
import { useState } from 'react'
import { ARENA_QUESTIONS } from './engine'
import { AutoDebateView } from './AutoDebateView'
import { DraftView } from './DraftView'
import { LibraryView } from './LibraryView'
import { SplitView } from './SplitView'

const TABS = [
  { k: 'split', label: '拆题台' },
  { k: 'draft', label: '稿件生成' },
  { k: 'arena', label: '攻防演练' },
  { k: 'library', label: '素材库' },
  { k: 'auto', label: '自动辩论' },
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
      {tab === 'auto' && <AutoDebateView />}
    </div>
  )
}

const TYPE_LABEL: Record<string, string> = {
  def: '定义战', std: '判准战', logic: '归谬逻辑',
  example: '例证攻防', value: '价值升维',
}

/** 攻防演练：抽题 → 自己想 15 秒 → 看应对要点 → 自评。
 *  错题本：「被打穿」的题记入 localStorage，后续抽题优先出这些——
 *  演练从随机变成针对性。评「妙极」则出库（已掌握）。 */
const MISTAKE_KEY = 'debater.drillMistakes'

function loadMistakes(): number[] {
  try {
    const v = JSON.parse(localStorage.getItem(MISTAKE_KEY) ?? '[]')
    return Array.isArray(v) ? v.filter((n) => Number.isInteger(n)) : []
  } catch { return [] }
}

function ArenaView() {
  const [idx, setIdx] = useState(0)
  const [showTip, setShowTip] = useState(false)
  const [log, setLog] = useState<string[]>([])
  const [mistakes, setMistakes] = useState<number[]>(loadMistakes)
  const q = ARENA_QUESTIONS[idx % ARENA_QUESTIONS.length]

  const next = () => {
    setShowTip(false)
    // 错题本非空时 50% 概率优先出错题（循环轮换），否则顺序出
    if (mistakes.length && Math.random() < 0.5) {
      const at = mistakes.indexOf(idx)
      const nextIdx = mistakes[(at + 1) % mistakes.length]
      setIdx(nextIdx)
      return
    }
    setIdx((i) => (i + 1) % ARENA_QUESTIONS.length)
  }

  const rate = (verdict: string) => {
    setLog((l) => [...l, `「${q.src}」${TYPE_LABEL[q.t] ?? q.t} → ${verdict}`])
    if (verdict === '被打穿') {
      setMistakes((m) => {
        const next = m.includes(idx) ? m : [...m, idx]
        try { localStorage.setItem(MISTAKE_KEY, JSON.stringify(next)) } catch { /* 忽略 */ }
        return next
      })
    } else if (verdict === '妙极') {
      setMistakes((m) => {
        const next = m.filter((n) => n !== idx)
        try { localStorage.setItem(MISTAKE_KEY, JSON.stringify(next)) } catch { /* 忽略 */ }
        return next
      })
    }
  }

  return (
    <div>
      <div className="prep-card">
        <div className="arena-meta">
          {q.src} · {TYPE_LABEL[q.t] ?? q.t}
          {mistakes.includes(idx) && <span style={{ color: 'var(--warn)' }}> · 错题</span>}
        </div>
        <div className="arena-q">{q.q}</div>
        <div className="prep-actions">
          <button className="btn-mini" onClick={next}>下一题 ▸</button>
          <button className="btn-mini" onClick={() => setShowTip((v) => !v)}>
            {showTip ? '收起要点' : '看应对要点'}
          </button>
        </div>
        {showTip && <div className="arena-tip">{q.tip}</div>}
        {showTip && (
          <div className="prep-actions" title="诚实自评：被打穿进错题本优先重练，妙极出库">
            <span className="muted">自评：</span>
            {['妙极', '稳住', '险胜', '被打穿'].map((v) => (
              <button key={v} className="btn-mini" onClick={() => rate(v)}>{v}</button>
            ))}
          </div>
        )}
        {mistakes.length > 0 && (
          <p className="hint">错题本：{mistakes.length} 题（优先重练；评「妙极」自动出库）</p>
        )}
        {log.length > 0 && (
          <ul className="prep-log">{log.map((x, i) => <li key={i}>{x}</li>)}</ul>
        )}
      </div>
    </div>
  )
}

/** 备赛模式容器：四个板块的子导航与切换。 */
import { useEffect, useRef, useState } from 'react'
import { ARENA_QUESTIONS } from './engine'
import { AutoDebateView } from './AutoDebateView'
import { DraftView } from './DraftView'
import { LibraryView } from './LibraryView'
import { SparringView } from './SparringView'
import { SplitView } from './SplitView'

const TABS = [
  { k: 'split', label: '拆题台' },
  { k: 'draft', label: '稿件生成' },
  { k: 'arena', label: '攻防演练' },
  { k: 'library', label: '素材库' },
  { k: 'sparring', label: '人机对练' },
  { k: 'auto', label: '自动辩论' },
] as const
type TabKey = (typeof TABS)[number]['k']

export default function PrepView() {
  const [tab, setTab] = useState<TabKey>('split')
  // 素材库「送入稿件」→ 自动跳到稿件生成（DraftView 挂载时取走 localStorage 交接）
  // 拆题台「数据三连 → 送入对练」→ 自动跳到人机对练（同款交接模式）
  useEffect(() => {
    const goDraft = () => setTab('draft')
    const goSparring = () => setTab('sparring')
    window.addEventListener('debater.prep-handoff', goDraft)
    window.addEventListener('debater.sparring-handoff', goSparring)
    return () => {
      window.removeEventListener('debater.prep-handoff', goDraft)
      window.removeEventListener('debater.sparring-handoff', goSparring)
    }
  }, [])
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
      {tab === 'sparring' && <SparringView />}
      {tab === 'auto' && <AutoDebateView />}
    </div>
  )
}

const TYPE_LABEL: Record<string, string> = {
  def: '定义战', std: '判准战', logic: '归谬逻辑',
  example: '例证攻防', value: '价值升维', data: '数据战',
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

/** 自定义演练题：实战后想练自己辩题的质询。追加在内置题之后（索引连续，错题本兼容）。 */
const CUSTOM_Q_KEY = 'debater.customQuestions'
/** 演练自评记录：刷新不丢（与错题本同生命周期）。 */
const DRILL_LOG_KEY = 'debater.drillLog'

interface DrillEntry { x: string; at: string }

/** 演练自评记录：新格式带时间戳（进度时间轴用），旧格式（纯字符串）兼容读入。 */
function loadDrillLog(): DrillEntry[] {
  try {
    const v = JSON.parse(localStorage.getItem(DRILL_LOG_KEY) ?? '[]')
    if (!Array.isArray(v)) return []
    return v
      .map((x) => (typeof x === 'string' ? { x, at: '' } : x))
      .filter((x) => typeof x?.x === 'string')
  } catch { return [] }
}

function saveDrillLog(log: DrillEntry[]): void {
  try { localStorage.setItem(DRILL_LOG_KEY, JSON.stringify(log.slice(-50))) } catch { /* 忽略 */ }
}

const dayOf = (at: string): string => (at ? at.slice(0, 10) : '（未记时间）')
const CUSTOM_SRC = '自定义'

interface CustomQ { t: 'def' | 'std' | 'logic' | 'example' | 'value' | 'data'; q: string }

function loadCustomQs(): CustomQ[] {
  try {
    const v = JSON.parse(localStorage.getItem(CUSTOM_Q_KEY) ?? '[]')
    return Array.isArray(v)
      ? v.filter((x: CustomQ) => typeof x?.q === 'string' && x.q.trim() && ['def', 'std', 'logic', 'example', 'value', 'data'].includes(x.t))
      : []
  } catch { return [] }
}

const QUICK_THINK_S = 15

function ArenaView() {
  const [idx, setIdx] = useState(0)
  /** 快思倒计时：真实比赛质询准备只有十几秒——练节奏，纯前端 */
  const [thinkLeft, setThinkLeft] = useState<number | null>(null)
  const thinkTick = useRef<ReturnType<typeof setInterval> | null>(null)
  const [showTip, setShowTip] = useState(false)
  const [log, setLog] = useState<DrillEntry[]>(loadDrillLog)
  const [mistakes, setMistakes] = useState<number[]>(loadMistakes)
  /** 错题列表展开态：只做展示与跳题，不新增状态来源 */
  const [showMistakes, setShowMistakes] = useState(false)
  /** 题型筛选：'all' 或五类之一。筛选后抽题只在池内循环。 */
  const [typeFilter, setTypeFilter] = useState<'all' | 'def' | 'std' | 'logic' | 'example' | 'value' | 'data'>('all')
  /** 自定义题：内置 28 题之后追加（索引连续，错题本的内置题索引不受影响） */
  const [customQs, setCustomQs] = useState<CustomQ[]>(loadCustomQs)
  const [newQ, setNewQ] = useState('')
  const [newQT, setNewQT] = useState<CustomQ['t']>('def')
  const [showAdd, setShowAdd] = useState(false)
  const allQs = [...ARENA_QUESTIONS, ...customQs.map((c) => ({ ...c, src: CUSTOM_SRC, tip: '' }))]
  const pool = allQs.map((q, i) => ({ q, i }))
    .filter(({ q }) => typeFilter === 'all' || q.t === typeFilter)
  const pos = Math.max(0, pool.findIndex(({ i }) => i === idx))
  const q = pool.length ? pool[pos]?.q ?? allQs[idx % allQs.length] : allQs[0]
  const inPool = pool.some(({ i }) => i === idx)

  const addCustom = () => {
    const text = newQ.trim()
    if (!text) return
    const next = [...customQs, { t: newQT, q: text }]
    setCustomQs(next)
    try { localStorage.setItem(CUSTOM_Q_KEY, JSON.stringify(next)) } catch { /* 忽略 */ }
    setNewQ('')
    // 新题立即可练：跳到它
    setIdx(ARENA_QUESTIONS.length + next.length - 1)
    setTypeFilter('all')
    setShowTip(false)
  }
  const removeCustom = (ci: number) => {
    const next = customQs.filter((_, k) => k !== ci)
    setCustomQs(next)
    try { localStorage.setItem(CUSTOM_Q_KEY, JSON.stringify(next)) } catch { /* 忽略 */ }
    // 同步错题本：被删题的全局索引 = 内置数 + ci。不修的话，错题本里它的索引
    // 悬空、其后自定义题的索引整体漂移——错题会指向别的题。
    const gi = ARENA_QUESTIONS.length + ci
    setMistakes((m) => {
      const next = m.filter((mi) => mi !== gi).map((mi) => (mi > gi ? mi - 1 : mi))
      try { localStorage.setItem(MISTAKE_KEY, JSON.stringify(next)) } catch { /* 忽略 */ }
      return next
    })
    setIdx(0)
  }

  useEffect(() => {
    if (thinkLeft === null) return
    if (thinkLeft <= 0) {
      const t = thinkTick.current
      if (t) clearInterval(t)
      setThinkLeft(0)
      return
    }
    thinkTick.current = setInterval(() => setThinkLeft((v) => (v === null ? null : v - 1)), 1000)
    return () => { if (thinkTick.current) clearInterval(thinkTick.current) }
  }, [thinkLeft !== null && thinkLeft > 0])

  const startThink = () => { setThinkLeft(QUICK_THINK_S) }
  /** 换题/跳题/筛选时停表 */
  const stopThink = () => { setThinkLeft(null) }

  /** 从错题本跳题：错题可能不在当前筛选池里，跳转即回全量，避免"点了没反应"的错觉 */
  const jumpToMistake = (mi: number) => {
    setTypeFilter('all')
    setIdx(mi)
    setShowTip(false)
    setShowMistakes(false)
    stopThink()
  }

  const next = () => {
    setShowTip(false)
    stopThink()
    if (!pool.length) return
    // 错题本非空且错题在当前池内时 50% 概率优先出错题（循环轮换），否则池内顺序出
    if (mistakes.length && Math.random() < 0.5) {
      const inPoolMistakes = mistakes.filter((mi) => pool.some(({ i }) => i === mi))
      if (inPoolMistakes.length) {
        const at = inPoolMistakes.indexOf(idx)
        const nextIdx = inPoolMistakes[(at + 1) % inPoolMistakes.length]
        setIdx(nextIdx)
        return
      }
    }
    setIdx(pool[(pos + 1) % pool.length].i)
  }

  const rate = (verdict: string) => {
    setLog((l) => {
      const next = [...l, { x: `「${q.src}」${TYPE_LABEL[q.t] ?? q.t} → ${verdict}`, at: new Date().toISOString() }]
      saveDrillLog(next)
      return next
    })
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
          {typeFilter !== 'all' && ` · 筛选：${TYPE_LABEL[typeFilter]}`}
        </div>
        <div className="arena-q">{q.q}</div>
        <div className="prep-actions">
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            题型
            <select
              className="text-input"
              style={{ width: 'auto' }}
              value={typeFilter}
              onChange={(e) => { setTypeFilter(e.target.value as typeof typeFilter); setShowTip(false) }}
            >
              <option value="all">全部</option>
              <option value="def">定义战</option>
              <option value="std">判准战</option>
              <option value="logic">归谬逻辑</option>
              <option value="example">例证攻防</option>
              <option value="value">价值升维</option>
              <option value="data">数据战</option>
            </select>
          </label>
          <button className="btn-mini" onClick={next} disabled={!pool.length}>下一题 ▸</button>
          {thinkLeft !== null ? (
            <span
              style={{ color: thinkLeft === 0 ? 'var(--warn)' : 'var(--accent)', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}
              title="真实比赛里质询准备只有十几秒——练的就是这个节奏"
            >
              {thinkLeft === 0 ? '该开口了' : `快思 ${thinkLeft}s`}
            </span>
          ) : (
            <button
              className="btn-mini"
              onClick={startThink}
              title={`开始 ${QUICK_THINK_S} 秒倒计时，练临场节奏`}
            >
              快思 15s
            </button>
          )}
          <button
            className="btn-mini"
            onClick={() => setShowTip((v) => !v)}
            disabled={!q.tip}
            title={q.tip ? undefined : '自定义题没有标准要点——你自己的应对就是要点'}
          >
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
        {mistakes.length > 0 && (() => {
          const dist: Record<string, number> = {}
          for (const mi of mistakes) {
            const t = allQs[mi]?.t
            if (t) dist[t] = (dist[t] ?? 0) + 1
          }
          const ranked = Object.entries(dist).sort((a, b) => b[1] - a[1])
          return (
            <p className="hint">
              错题本：{mistakes.length} 题（优先重练；评「妙极」自动出库）
              {ranked.length > 0 && (
                <span title="按题型聚合——最弱的一类排最前">
                  {' · 弱项：'}{ranked.map(([t, n]) => `${TYPE_LABEL[t] ?? t} ${n}`).join(' · ')}
                </span>
              )}
              <button className="btn-mini" style={{ marginLeft: 8 }} onClick={() => setShowMistakes((v) => !v)}>
                {showMistakes ? '收起错题' : '看错题'}
              </button>
            </p>
          )
        })()}
        {log.length >= 3 && (() => {
          const byDay: Record<string, { total: number; broken: number }> = {}
          for (const e of log) {
            const d = dayOf(e.at)
            byDay[d] = byDay[d] ?? { total: 0, broken: 0 }
            byDay[d].total += 1
            if (e.x.endsWith('被打穿')) byDay[d].broken += 1
          }
          const days = Object.keys(byDay).sort().reverse().slice(0, 7)
          const verdictCount = (v: string) => log.filter((e) => e.x.endsWith(`→ ${v}`)).length
          return (
            <details className="draft-data-check">
              <summary className="muted">训练进度：{log.length} 次演练，被打穿 {verdictCount('被打穿')} 次（点开看按天分布）</summary>
              <ul className="prep-log">
                {days.map((d) => (
                  <li key={d}>
                    {d}——演练 {byDay[d].total} 次{byDay[d].broken > 0 ? `，被打穿 ${byDay[d].broken}` : '，零被打穿'}
                  </li>
                ))}
              </ul>
              <p className="hint">
                累计：妙极 {verdictCount('妙极')} · 稳住 {verdictCount('稳住')} · 险胜 {verdictCount('险胜')} · 被打穿 {verdictCount('被打穿')}
              </p>
            </details>
          )
        })()}
        <p className="hint">
          自定义题：{customQs.length} 题（实战后练自己的质询）
          <button className="btn-mini" style={{ marginLeft: 8 }} onClick={() => setShowAdd((v) => !v)}>
            {showAdd ? '收起' : '+ 添加'}
          </button>
        </p>
        {showAdd && (
          <div>
            <textarea
              className="text-input"
              rows={2}
              value={newQ}
              onChange={(e) => setNewQ(e.target.value)}
              placeholder="输入你的质询题，例：您方判准里的「效率」包不包括程序正义？"
            />
            <div className="prep-actions">
              <select className="text-input" style={{ width: 'auto' }} value={newQT} onChange={(e) => setNewQT(e.target.value as CustomQ['t'])}>
                <option value="def">定义战</option>
                <option value="std">判准战</option>
                <option value="logic">归谬逻辑</option>
                <option value="example">例证攻防</option>
                <option value="value">价值升维</option>
              </select>
              <button className="btn-mini" disabled={!newQ.trim()} onClick={addCustom}>加入题库并开练</button>
            </div>
            {customQs.length > 0 && (
              <ul className="prep-log">
                {customQs.map((c, ci) => (
                  <li key={ci}>
                    <span style={{ fontSize: 12 }}>{TYPE_LABEL[c.t]}｜{c.q.length > 40 ? c.q.slice(0, 40) + '…' : c.q}</span>
                    <button className="btn-mini danger" style={{ marginLeft: 8 }} title="删除这条自定义题" onClick={() => removeCustom(ci)}>删</button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {showMistakes && mistakes.length > 0 && (
          <ul className="prep-log">
            {mistakes.map((mi) => {
              const mq = allQs[mi]
              if (!mq) return null
              return (
                <li key={mi}>
                  <button className="btn-mini" title="跳到这道题重练" onClick={() => jumpToMistake(mi)}>
                    {TYPE_LABEL[mq.t] ?? mq.t}｜{mq.q.length > 44 ? mq.q.slice(0, 44) + '…' : mq.q}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
        {log.length > 0 && (
          <ul className="prep-log">
            {log.map((e, i) => (
              <li key={i}>
                {e.x}
                {e.at && <span className="muted" style={{ marginLeft: 8, fontSize: 11 }}>{e.at.slice(5, 16).replace('T', ' ')}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

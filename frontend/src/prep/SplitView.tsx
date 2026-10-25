/** 拆题台：任意辩题 → 题型 / 双方主张 / 定义与判准建议 / 核心交锋点。本地引擎秒出，AI 可加深。 */
import { useMemo, useState } from 'react'
import {
  ARENA_QUESTIONS, claimOf, detectType, engine, matchBank,
} from './engine'
import { Section, useCopy } from './ui'
import { prepAI as apiPrepAI } from '../api'

export function SplitView() {
  const [topic, setTopic] = useState('')
  const [aiText, setAiText] = useState('')
  const [aiBusy, setAiBusy] = useState(false)
  const [aiErr, setAiErr] = useState('')
  const [copied, copy] = useCopy()

  const type = topic.trim() ? detectType(topic) : null
  const bank = topic.trim() ? matchBank(topic) : null
  const r = topic.trim() ? engine(topic, 'pro', type || 'value') : null
  const pro = topic.trim() ? claimOf(topic, 'pro') : ''
  const con = topic.trim() ? claimOf(topic, 'con') : ''
  const typeLabel = { value: '价值辩题', fact: '事实辩题', policy: '政策辩题' }[type || 'value'] ?? ''

  const summary = useMemo(() => {
    if (!r) return ''
    return [
      `辩题：${topic}（${typeLabel}）`,
      `正方主张：${pro}`,
      `反方主张：${con}`,
      bank ? `命中内置辩题库：${bank.name}` : '',
      `正方定义建议：${r.def}`,
      `正方判准建议：${r.std}`,
      `正方论点骨架：${r.pts.join(' / ')}`,
      `价值落点：${r.val}`,
    ].filter(Boolean).join('\n')
  }, [r, topic, typeLabel, pro, con, bank])

  const runAI = async () => {
    if (!topic.trim() || aiBusy) return
    setAiBusy(true); setAiErr(''); setAiText('')
    try {
      const data = await apiPrepAI({ task: 'split', topic, side: pro ? '正方' : '正方' })
      if (data.ok && data.text) setAiText(data.text)
      else setAiErr(data.error ?? '未知错误')
    } catch (e) {
      setAiErr(String(e))
    } finally {
      setAiBusy(false)
    }
  }

  return (
    <div>
      <Section title="拆题台" tip="输入辩题，本地引擎即时判定题型、拆出双方主张与立论骨架；「AI 深拆」走云端（1 次上游调用）">
        <input
          className="text-input"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="输入完整辩题，例：AI 生成内容应不应该强制标注"
        />
        <div className="prep-actions">
          <button className="btn-mini" disabled={aiBusy || !topic.trim()} onClick={() => void runAI()}>
            {aiBusy ? '深拆中…' : 'AI 深拆'}
          </button>
          {summary && (
            <button className="btn-mini" title="复制拆题结果" onClick={() => copy(summary)}>
              {copied ? '✓ 已复制' : '复制'}
            </button>
          )}
        </div>
      </Section>

      {r && (
        <Section title={`拆题结果 · ${typeLabel}${bank ? ' · 命中辩题库' : ''}`}>
          <div className="vs-box">
            <div className="vs-side pro"><b>正方</b><p>{pro}</p></div>
            <div className="vs-mid">对</div>
            <div className="vs-side con"><b>反方</b><p>{con}</p></div>
          </div>
          <div className="split-block">
            <h4>正方定义建议</h4><p>{r.def}</p>
            <h4>正方判准建议</h4><p>{r.std}</p>
            <h4>论点骨架（正方）</h4>
            <ul>{r.pts.map((p, i) => <li key={i}>{p}</li>)}</ul>
            <h4>价值落点</h4><p>{r.val}</p>
            <p className="muted">来源：{r.src}</p>
          </div>
        </Section>
      )}

      {aiText && (
        <Section title="AI 深拆">
          <pre className="prep-ai-out">{aiText}</pre>
          <button className="btn-mini" onClick={() => copy(aiText)}>{copied ? '✓ 已复制' : '复制'}</button>
        </Section>
      )}
      {aiErr && <p className="error">{aiErr}</p>}

      <Section title="攻防演练题库" tip={`真实交锋提炼的质询题（共 ${ARENA_QUESTIONS.length} 题）：先自己想，再看应对要点`}>
        <ArenaList />
      </Section>
    </div>
  )
}

function ArenaList() {
  const [idx, setIdx] = useState(0)
  const [showTip, setShowTip] = useState(false)
  const q = ARENA_QUESTIONS[idx % ARENA_QUESTIONS.length]
  return (
    <div>
      <div className="arena-meta">{q.src} · {q.t === 'def' ? '定义战' : q.t === 'std' ? '判准战' : q.t === 'logic' ? '归谬逻辑' : q.t === 'example' ? '例证攻防' : q.t === 'value' ? '价值升维' : q.t}</div>
      <div className="arena-q">{q.q}</div>
      <div className="prep-actions">
        <button className="btn-mini" onClick={() => { setIdx((i) => (i + 1) % ARENA_QUESTIONS.length); setShowTip(false) }}>下一题 ▸</button>
        <button className="btn-mini" onClick={() => setShowTip((v) => !v)}>{showTip ? '收起要点' : '看应对要点'}</button>
      </div>
      {showTip && <div className="arena-tip">{q.tip}</div>}
    </div>
  )
}

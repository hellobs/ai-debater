/** 素材库：例证（辩题库 / 主题 / 人物，全部正反双向）与金句，搜索 + 一键复制。 */
import { useMemo, useState } from 'react'
import DATA from '../data/prep/debate-data.json'
import { Section, useCopy } from './ui'
import type { PersonEntry, QuoteEntry } from './engine'

/** 素材 → 稿件生成的交接（localStorage 单条，取走即清）：跨 tab 组件传递的最短路径 */
function handoff(entry: { label: string; text: string }): void {
  try {
    localStorage.setItem('debater.prepHandoff', JSON.stringify(entry))
  } catch { /* 隐私模式忽略 */ }
}

const BANK = DATA.BANK
const THEMES = DATA.THEME_EX
const PEOPLE = DATA.PERSON_EX as PersonEntry[]
const QUOTES = DATA.QUOTES as QuoteEntry[]

type Tab = 'bank' | 'person' | 'quote'

export function LibraryView() {
  const [tab, setTab] = useState<Tab>('person')
  const [q, setQ] = useState('')
  const [copied, copy] = useCopy()

  const low = q.trim().toLowerCase()
  const hit = (s: string) => !low || s.toLowerCase().includes(low)

  const people = useMemo(
    () => PEOPLE.filter((p) => hit(p.n + p.f + p.pro + p.con + p.k.join(' '))),
    [low],
  )
  const banks = useMemo(() => BANK.filter((b) => hit(b.name + b.k.join(' '))), [low])
  const quotes = useMemo(() => QUOTES.filter((x) => hit(x.q + x.c + (x.src || ''))), [low])

  const TABS: [Tab, string][] = [
    ['person', `例证 · 人物（${people.length}）`],
    ['bank', `辩题库（${banks.length}）`],
    ['quote', `金句（${quotes.length}）`],
  ]

  return (
    <div>
      <Section title="素材库" tip="全部素材带正反双向用法：同一个例子双方都能用，胜负在解释框架。搜索后点「复制」直接进稿">
        <input
          className="text-input"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="搜索关键词，例：AI / 金钱 / 项羽 / 孤独…"
        />
        <div className="prep-tabs">
          {TABS.map(([k, label]) => (
            <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{label}</button>
          ))}
        </div>
      </Section>

      {tab === 'person' && (
        <>
          {people.map((p) => (
            <Section key={p.n} title={p.n}>
              <p className="prep-fact">{p.f}</p>
              <div className="prep-duo">
                <div className="pro"><b>正方用法</b><p>{p.pro}</p></div>
                <div className="con"><b>反方用法</b><p>{p.con}</p></div>
              </div>
              {p.tip && <p className="muted">提示：{p.tip}</p>}
              <div className="prep-actions">
                <button className="btn-mini" onClick={() => copy(`${p.f}（正方：${p.pro}｜反方：${p.con}）`)}>
                  {copied ? '✓' : '复制'}
                </button>
                <button
                  className="btn-mini"
                  title="送入「稿件生成」的例证栏"
                  onClick={() => handoff({ label: p.n, text: `${p.n}——${p.f}（正方：${p.pro}｜反方：${p.con}）` })}
                >
                  送入稿件
                </button>
              </div>
            </Section>
          ))}
          {!people.length && <p className="muted">无匹配例证。</p>}
        </>
      )}

      {tab === 'bank' && (
        <>
          {banks.map((b) => (
            <Section key={b.name} title={b.name}>
              <div className="prep-duo">
                <div className="pro"><b>正方 · 定义</b><p>{b.pro.def}</p></div>
                <div className="con"><b>反方 · 定义</b><p>{b.con.def}</p></div>
              </div>
              <details>
                <summary className="muted">判准与论点</summary>
                <div className="prep-duo">
                  <div className="pro"><p>{b.pro.std}</p><ul>{b.pro.pts.map((x, i) => <li key={i}>{x}</li>)}</ul><p>{b.pro.val}</p></div>
                  <div className="con"><p>{b.con.std}</p><ul>{b.con.pts.map((x, i) => <li key={i}>{x}</li>)}</ul><p>{b.con.val}</p></div>
                </div>
              </details>
            </Section>
          ))}
          {!banks.length && <p className="muted">无匹配辩题。</p>}
        </>
      )}

      {tab === 'quote' && (
        <>
          {quotes.map((x, i) => (
            <Section key={i} title={x.c} tip={x.src}>
              <p className="prep-quote">「{x.q}」</p>
              <div className="prep-actions">
                {x.src && <span className="muted">{x.src}</span>}
                <button className="btn-mini" onClick={() => copy(x.q)}>{copied ? '✓' : '复制'}</button>
                <button
                  className="btn-mini"
                  title="送入「稿件生成」的金句栏"
                  onClick={() => handoff({ label: x.c, text: x.q })}
                >
                  送入稿件
                </button>
              </div>
            </Section>
          ))}
          {!quotes.length && <p className="muted">无匹配金句。</p>}
        </>
      )}
    </div>
  )
}

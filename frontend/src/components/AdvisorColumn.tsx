import { useEffect, useState } from 'react'
import { cardFor } from '../adopt'
import { saveFeedback } from '../api'
import type {
  AdoptCard,
  AdvisorResult,
  AuditFinding,
  Conflict,
  MethodNote,
  Rebuttal,
  RiskItem,
} from '../types'

/** 一行可编辑文本（点进去就能改，对应参考图里"生成结果可直接点击修改"） */
function Editable(props: {
  label?: string
  value: string
  rows?: number
  onChange: (v: string) => void
}) {
  const { label, value, rows = 1, onChange } = props
  return (
    <div className="field">
      {label && <span className="field-label">{label}</span>}
      <textarea
        className="field-input"
        rows={rows}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  )
}

/**
 * 卡片底部的「采纳为我方主张」。反驳手 / 策略师 / 风险提示员三路共用。
 * `card` 为 null（该条缺关键字段）或未传 `onAdopt` 时不渲染。
 */
function AdoptButton(props: {
  card: AdoptCard | null
  adopted: Set<string>
  busy: boolean
  onAdopt?: (card: AdoptCard) => void
}) {
  const { card, adopted, busy, onAdopt } = props
  if (!onAdopt || !card) return null
  const isAdopted = adopted.has(card.claim)
  return (
    <div className="card-actions">
      <button
        className="btn-adopt"
        disabled={busy || isAdopted}
        onClick={() => onAdopt(card)}
      >
        {isAdopted ? '已采纳' : '采纳为我方主张'}
      </button>
    </div>
  )
}

function RebuttalList(props: {
  result: AdvisorResult
  conflicts: Conflict[]
  adopted: Set<string>
  busy: boolean
  onAdopt?: (card: AdoptCard) => void
}) {
  const { result, conflicts, adopted, busy, onAdopt } = props
  const [items, setItems] = useState<Rebuttal[]>([])

  useEffect(() => {
    setItems(Array.isArray(result.payload) ? (result.payload as Rebuttal[]) : [])
  }, [result])

  const patch = (i: number, key: keyof Rebuttal, v: string) =>
    setItems((prev) => prev.map((it, idx) => (idx === i ? { ...it, [key]: v } : it)))

  const conflictOf = (claim: string) =>
    conflicts.find((c) => c.new_claim.trim() === claim.trim())

  if (!items.length) return <p className="muted">未返回反驳要点。</p>

  return (
    <>
      {items.map((it, i) => {
        const conflict = conflictOf(it.claim)
        const card = cardFor('rebuttal', it)
        const isAdopted = card ? adopted.has(card.claim) : false
        return (
          <article className={`card${conflict ? ' conflicted' : ''}`} key={i}>
            <div className="card-head">
              <span className="badge badge-point">论点 {i + 1}</span>
              {conflict && <span className="badge badge-warn">与台账冲突</span>}
              {isAdopted && <span className="badge badge-ok">已在台账</span>}
            </div>
            <Editable value={it.claim} rows={2} onChange={(v) => patch(i, 'claim', v)} />
            <div className="syllogism">
              <Editable label="大前提" value={it.major_premise} rows={3}
                onChange={(v) => patch(i, 'major_premise', v)} />
              <Editable label="小前提" value={it.minor_premise} rows={3}
                onChange={(v) => patch(i, 'minor_premise', v)} />
              <Editable label="结　论" value={it.conclusion} rows={2}
                onChange={(v) => patch(i, 'conclusion', v)} />
            </div>
            {conflict && <p className="conflict-note">{conflict.reason}</p>}
            <AdoptButton card={card} adopted={adopted} busy={busy} onAdopt={onAdopt} />
          </article>
        )
      })}
    </>
  )
}

function QuestionList({ result }: { result: AdvisorResult }) {
  const [items, setItems] = useState<string[]>([])
  useEffect(() => {
    setItems(Array.isArray(result.payload) ? (result.payload as string[]) : [])
  }, [result])

  if (!items.length) return <p className="muted">未返回质询问题。</p>

  return (
    <>
      {items.map((q, i) => (
        <article className="card" key={i}>
          <div className="card-head">
            <span className="badge badge-q">质询 {i + 1}</span>
          </div>
          <Editable value={q} rows={2}
            onChange={(v) => setItems((prev) => prev.map((x, idx) => (idx === i ? v : x)))} />
        </article>
      ))}
    </>
  )
}

function AuditList({ result }: { result: AdvisorResult }) {
  const [items, setItems] = useState<AuditFinding[]>([])
  useEffect(() => {
    setItems(Array.isArray(result.payload) ? (result.payload as AuditFinding[]) : [])
  }, [result])

  const patch = (i: number, key: keyof AuditFinding, v: string) =>
    setItems((prev) => prev.map((it, idx) => (idx === i ? { ...it, [key]: v } : it)))

  if (!items.length) {
    return <p className="muted">未发现明显谬误（不许硬找）。</p>
  }

  return (
    <>
      {items.map((it, i) => (
        <article className="card" key={i}>
          <div className="card-head">
            <span className="badge badge-fallacy">{it.fallacy || '谬误'}</span>
          </div>
          <Editable label="对方原话" value={it.quote} rows={2}
            onChange={(v) => patch(i, 'quote', v)} />
          <Editable label="说明" value={it.explain} rows={2}
            onChange={(v) => patch(i, 'explain', v)} />
        </article>
      ))}
    </>
  )
}

function StrategyList(props: {
  result: AdvisorResult
  adopted: Set<string>
  busy: boolean
  onAdopt?: (card: AdoptCard) => void
}) {
  const { result, adopted, busy, onAdopt } = props
  const [items, setItems] = useState<MethodNote[]>([])
  useEffect(() => {
    setItems(Array.isArray(result.payload) ? (result.payload as MethodNote[]) : [])
  }, [result])

  const patch = (i: number, key: keyof MethodNote, v: string) =>
    setItems((prev) => prev.map((it, idx) => (idx === i ? { ...it, [key]: v } : it)))

  if (!items.length) return <p className="muted">未识别到衡量尺度之争。</p>

  return (
    <>
      {items.map((it, i) => {
        const card = cardFor('strategy', it)
        const isAdopted = card ? adopted.has(card.claim) : false
        return (
          <article className="card" key={i}>
            <div className="card-head">
              <span className="badge badge-method">{it.opponent_method || '对方的尺度'}</span>
              <span className="arrow-hint">→</span>
              <span className="badge badge-ours">{it.our_method || '我方的尺度'}</span>
              {isAdopted && <span className="badge badge-ok">已在台账</span>}
            </div>
            <Editable label="对方以此方法的作用" value={it.opponent_effect} rows={2}
              onChange={(v) => patch(i, 'opponent_effect', v)} />
            <Editable label="为何我方主张的方法应优先" value={it.counter} rows={3}
              onChange={(v) => patch(i, 'counter', v)} />
            <AdoptButton card={card} adopted={adopted} busy={busy} onAdopt={onAdopt} />
          </article>
        )
      })}
    </>
  )
}

function RiskList(props: {
  result: AdvisorResult
  adopted: Set<string>
  busy: boolean
  onAdopt?: (card: AdoptCard) => void
}) {
  const { result, adopted, busy, onAdopt } = props
  const [items, setItems] = useState<RiskItem[]>([])
  useEffect(() => {
    setItems(Array.isArray(result.payload) ? (result.payload as RiskItem[]) : [])
  }, [result])

  const patch = (i: number, key: keyof RiskItem, v: string) =>
    setItems((prev) => prev.map((it, idx) => (idx === i ? { ...it, [key]: v } : it)))

  if (!items.length) return <p className="muted">未识别到明显风险。</p>

  return (
    <>
      {items.map((it, i) => {
        const card = cardFor('risk', it)
        const isAdopted = card ? adopted.has(card.claim) : false
        return (
          <article className="card card-risk" key={i}>
            <div className="card-head">
              <span className="badge badge-risk">{it.kind || '风险'}</span>
              {isAdopted && <span className="badge badge-ok">已在台账</span>}
            </div>
            <Editable value={it.risk} rows={2} onChange={(v) => patch(i, 'risk', v)} />
            <Editable label="应对" value={it.suggestion} rows={2}
              onChange={(v) => patch(i, 'suggestion', v)} />
            <AdoptButton card={card} adopted={adopted} busy={busy} onAdopt={onAdopt} />
          </article>
        )
      })}
    </>
  )
}

/** 反馈闭环的界面端：评分（1–5 星）+ 勾选「收录为训练样本」，点击即提交。
 *  数据去向：/api/feedback → 导出脚本按"勾选+评分线"筛训练样本（app/feedback.py）。 */
function FeedbackRow(props: { sessionId: string; advisor: string }) {
  const { sessionId, advisor } = props
  const [rating, setRating] = useState<number | null>(null)
  const [selected, setSelected] = useState(false)
  const [done, setDone] = useState('')

  const submit = async (r: number | null, sel: boolean) => {
    try {
      await saveFeedback(sessionId, advisor, r, sel)
      setDone('已记录')
    } catch {
      setDone('提交失败')
    }
  }

  return (
    <div className="fb-row">
      <span className="stars" title="给这一路的本轮回答评分（1–5）">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            className={`star${(rating ?? 0) >= n ? ' on' : ''}`}
            aria-label={`${n} 星`}
            onClick={() => { setRating(n); void submit(n, selected) }}
          >
            ★
          </button>
        ))}
      </span>
      <button
        className={`btn-mini${selected ? ' chip-on' : ''}`}
        title="勾选后，导出脚本会把这条产出收进训练样本（人工勾选 + 评分≥4 双门槛）"
        onClick={() => { setSelected(!selected); void submit(rating, !selected) }}
      >
        {selected ? '✓ 已收录' : '收录样本'}
      </button>
      {done && <span className="muted">{done}</span>}
    </div>
  )
}

export default function AdvisorColumn(props: {
  label: string
  /** 场景领域。空 = 通用；非空则标注这一路是该场景专用的。 */
  domain?: string
  result?: AdvisorResult
  running: boolean
  conflicts: Conflict[]
  adopted: Set<string>
  busy: boolean
  onAdopt?: (card: AdoptCard) => void
  /** 反馈需要挂会话；为空（后端未连）时不显示反馈控件 */
  sessionId?: string | null
}) {
  const { label, domain, result, running, conflicts, adopted, busy, onAdopt, sessionId } = props
  /** 三条可采纳路的公共传参；质询 / 审计两路不用（详见 adopt.ts 说明）。 */
  const adoptProps = { adopted, busy, onAdopt }

  return (
    <section className="column">
      <header className="column-head">
        <h3>
          {label}
          {domain && <span className="roster-tag" title={`这一路是「${domain}」场景专用`}>{domain}</span>}
        </h3>
        <span className="column-meta">
          {result
            ? `${result.status === 'ok' ? '' : result.status + ' · '}${result.latency_s}s`
            : running
              ? '分析中…'
              : '待分析'}
        </span>
      </header>

      <div className="column-body">
        {result?.status === 'error' && (
          <p className="error">调用失败：{result.error}</p>
        )}
        {result?.status === 'timeout' && (
          <p className="warn-block">
            未在预算内返回（{result.latency_s}s 截断）。放宽「时间预算」重跑可补。
          </p>
        )}
        {result?.status === 'empty' && <p className="muted">未返回内容。</p>}

        {result?.status === 'ok' && result.kind === 'rebuttal' && (
          <RebuttalList result={result} conflicts={conflicts} {...adoptProps} />
        )}
        {result?.status === 'ok' && result.kind === 'questions' && (
          <QuestionList result={result} />
        )}
        {result?.status === 'ok' && result.kind === 'audit' && (
          <AuditList result={result} />
        )}
        {result?.status === 'ok' && result.kind === 'strategy' && (
          <StrategyList result={result} {...adoptProps} />
        )}
        {result?.status === 'ok' && result.kind === 'risk' && (
          <RiskList result={result} {...adoptProps} />
        )}

        {!result && !running && (
          <p className="muted">提交后并行出建议。</p>
        )}

        {result?.status === 'ok' && sessionId && (
          <FeedbackRow sessionId={sessionId} advisor={result.advisor} />
        )}
      </div>
    </section>
  )
}

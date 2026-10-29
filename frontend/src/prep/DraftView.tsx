/** 稿件生成：结构化表单 → 本地引擎自动供料 → 精修 → 成稿预览（字数/时长计量）→ 复制。
 *  AI 两键：供料（AI 填表）/ 成稿（AI 展开），都走 /api/prep/ai（计费）。 */
import { useEffect, useMemo, useState } from 'react'
import { detectType, engine, extractDataPoints, tripleProbe, type TopicType } from './engine'
import { downloadDraftDocx } from './AutoDebateView'
import { Editable, fmtDuration, Section, useCopy } from './ui'
import { prepAI } from '../api'

const FIELDS = ['def', 'std', 'a1', 'a2', 'a3', 'quote', 'val'] as const
type FieldKey = (typeof FIELDS)[number]

const LABELS: Record<FieldKey, string> = {
  def: '我方定义',
  std: '我方判准',
  a1: '论点一',
  a2: '论点二',
  a3: '论点三（可选）',
  quote: '金句 / 关键例证',
  val: '价值落点',
}

const KINDS = [
  { v: 'one', label: '一辩立论稿' },
  { v: 'cross', label: '攻辩问题链' },
  { v: 'close', label: '结辩稿' },
] as const

const LENGTHS = [
  { v: 600, label: '2 分钟' },
  { v: 900, label: '3 分钟' },
  { v: 1050, label: '3 分半' },
]

export function DraftView() {
  const [topic, setTopic] = useState('')
  const [side, setSide] = useState<'pro' | 'con'>('pro')
  const [kind, setKind] = useState<'one' | 'cross' | 'close'>('one')
  const [target, setTarget] = useState(900)
  const [form, setForm] = useState<Record<FieldKey, string>>({
    def: '', std: '', a1: '', a2: '', a3: '', quote: '', val: '',
  })
  const [src, setSrc] = useState('')
  const [busy, setBusy] = useState<'' | 'supply' | 'draft'>('')
  const [err, setErr] = useState('')
  const [copied, copy] = useCopy()
  const [aiDraft, setAiDraft] = useState('')
  /** 素材库「送入稿件」的交接：挂载时取走并追加进金句/例证栏（取走即清） */
  const [handoffNote, setHandoffNote] = useState('')
  useEffect(() => {
    try {
      const raw = localStorage.getItem('debater.prepHandoff')
      if (!raw) return
      const entry = JSON.parse(raw) as { label: string; text: string }
      localStorage.removeItem('debater.prepHandoff')
      setForm((f) => ({
        ...f,
        quote: f.quote ? f.quote + '；' + entry.text : entry.text,
      }))
      setHandoffNote(`已从素材库带入：${entry.label}`)
    } catch { /* 格式错/隐私模式：静默跳过 */ }
  }, [])

  const setField = (k: FieldKey) => (v: string) => {
    setAiDraft('')   // 用户改了材料 → 旧的 AI 成稿预览就是陈旧信息，回本地组稿
    setForm((f) => ({ ...f, [k]: v }))
  }

  /** 本地引擎自动供料：表单空时填入引擎结果，回填后供人精修 */
  const supplyLocal = () => {
    if (!topic.trim()) return
    const type: TopicType = detectType(topic)
    const r = engine(topic, side, type)
    setForm((f) => ({
      def: f.def || r.def,
      std: f.std || r.std,
      a1: f.a1 || r.pts[0] || '',
      a2: f.a2 || r.pts[1] || '',
      a3: f.a3 || r.pts[2] || '',
      quote: f.quote || r.quotes.join('；'),
      val: f.val || r.val,
    }))
    setSrc(r.src)
  }

  /** 组稿（本地，无 AI）：把表单内容按结构拼成全文 */
  const draft = useMemo(() => {
    const f = form
    const PH = (s: string) => `【${s}】`
    const sideName = side === 'pro' ? '正方' : '反方'
    const parts: string[] = []
    if (kind === 'one') {
      parts.push('谢谢主席，问候在场各位。')
      parts.push(`一 · 开宗明义（定义）\n${f.def || PH('请补充关键词定义')}`)
      parts.push(`二 · 判准\n${f.std ? `故我方判断本题的标准在于：${f.std}。基于此，我方论证如下：` : PH('请补充判准')}`)
      const useN = target >= 750 ? 3 : 2
      const pts = [[f.a1, '机制/影响面切入'], [f.a2, '后果/时效切入'], [f.a3, '损益比/兜底']]
      for (let i = 0; i < useN; i++) {
        parts.push(`三·论点${i + 1}\n${pts[i][0] || PH(pts[i][1])}`)
      }
      parts.push(`结语\n${f.val || ''}${f.quote ? f.quote + '。' : ''}综上所述，我方坚定认为：${topic || '……'}。谢谢大家！`)
    } else if (kind === 'cross') {
      parts.push(`攻辩问题链（${sideName}）`)
      const qs = [f.a1, f.a2, f.a3].filter(Boolean)
      if (!qs.length) parts.push(PH('每个问题=封闭式提问+预设对方两种答法+追击路线'))
      qs.forEach((q, i) => parts.push(`问题 ${i + 1}\n${q}`))
    } else {
      parts.push('先破：')
      parts.push(f.a1 || PH('点出对方全场未解决的关键问题（用第一/第二）'))
      parts.push('再立：')
      parts.push(f.a2 || PH('两句话收拢本方论证链'))
      parts.push(`升华\n${f.val || f.quote || PH('价值落点，克制准确')}`)
    }
    return parts.join('\n\n')
  }, [form, kind, side, target, topic])

  const words = draft.replace(/\s/g, '').length

  const callAI = async (task: 'supply' | 'draft') => {
    if (busy || !topic.trim()) return
    setBusy(task); setErr('')
    try {
      const data = await prepAI({ task, topic, side: side === 'pro' ? '正方' : '反方', materials: { ...form } })
      if (!data.ok || !data.text) { setErr(data.error ?? '未知错误'); return }
      if (task === 'supply') {
        // AI 供料：尝试解析 JSON 回填表单；解析失败则原样展示在 def
        try {
          const obj = JSON.parse(data.text.replace(/```[a-zA-Z]*\s*/g, '').trim())
          setForm((f) => ({
            def: f.def || obj.def || '',
            std: f.std || obj.std || '',
            a1: f.a1 || obj.a1 || '',
            a2: f.a2 || obj.a2 || '',
            a3: f.a3 || obj.a3 || '',
            quote: f.quote || (obj.quotes || []).join?.('；') || '',
            val: f.val || obj.val || '',
          }))
          setSrc('AI 供料')
        } catch {
          setForm((f) => ({ ...f, def: f.def || data.text! }))
          setSrc('AI 供料（非 JSON，已放定义栏）')
        }
      } else {
        // AI 成稿：原样展示（Markdown），替换预览
        setForm((f) => ({ ...f, def: f.def, a1: f.a1 }))
        setSrc('AI 成稿')
        setAiDraft(data.text)
      }
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy('')
    }
  }

  const [copiedText, setCopiedText] = useState('')

  return (
    <div>
      <Section title="稿件生成" tip="本地引擎自动供料 → 精修 → 成稿；AI 供料/AI 成稿走云端（各 1 次上游调用）">
        <input
          className="text-input"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="输入完整辩题，例：AI 生成内容应不应该强制标注"
        />
        <div className="prep-grid">
          <label>持方
            <select className="text-input" value={side} onChange={(e) => setSide(e.target.value as 'pro' | 'con')}>
              <option value="pro">正方</option>
              <option value="con">反方</option>
            </select>
          </label>
          <label>类型
            <select className="text-input" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
              {KINDS.map((k) => <option key={k.v} value={k.v}>{k.label}</option>)}
            </select>
          </label>
          <label>时长
            <select className="text-input" value={target} onChange={(e) => setTarget(Number(e.target.value))}>
              {LENGTHS.map((l) => <option key={l.v} value={l.v}>{l.label}</option>)}
            </select>
          </label>
        </div>
        <div className="prep-actions">
          <button className="btn-mini" onClick={supplyLocal} disabled={!topic.trim()}>引擎供料</button>
          <button className="btn-mini" onClick={() => void callAI('supply')} disabled={busy !== '' || !topic.trim()}>
            {busy === 'supply' ? 'AI 供料中…' : 'AI 供料（1 次调用）'}
          </button>
          <button className="btn-mini" onClick={() => void callAI('draft')} disabled={busy !== '' || !topic.trim()}>
            {busy === 'draft' ? 'AI 成稿中…' : 'AI 成稿（1 次调用）'}
          </button>
          <button className="btn-mini" onClick={() => { setForm({ def: '', std: '', a1: '', a2: '', a3: '', quote: '', val: '' }); setSrc(''); setAiDraft(''); setHandoffNote('') }}>清空</button>
        </div>
        {src && <span className="hint">材料来源：{src}</span>}
        {handoffNote && <span className="hint">{handoffNote}</span>}
        {err && <p className="error">{err}</p>}
      </Section>

      <Section title="材料（可直接改）">
        {FIELDS.map((k) => (
          <Editable key={k} label={LABELS[k]} value={form[k]} rows={k === 'def' || k === 'std' ? 2 : 3} onChange={setField(k)} />
        ))}
      </Section>

      <Section title="稿件预览">
        <div className="prep-actions">
          <button className="btn-mini" onClick={() => copy(aiDraft || draft)}>
            {copied ? '✓ 已复制' : '复制全文'}
          </button>
          <button
            className="btn-mini"
            title="下载 Markdown 文件"
            onClick={() => {
              const blob = new Blob([aiDraft || draft], { type: 'text/markdown;charset=utf-8' })
              const url = URL.createObjectURL(blob)
              const a = document.createElement('a')
              a.href = url; a.download = `${topic || '备赛稿'}.md`; a.click()
              URL.revokeObjectURL(url)
            }}
          >
            下载 .md
          </button>
          <button
            className="btn-mini"
            title="下载 Word 文件（后端 python-docx 直出）"
            onClick={() => void downloadDraftDocx(topic || '备赛稿', aiDraft || draft)}
          >
            下载 .docx
          </button>
        </div>
        <pre className="prep-draft">{aiDraft || draft}</pre>
        <div className="prep-meter">
          <span>字数 <b>{words}</b></span>
          <span>预计时长 <b>{fmtDuration(words)}</b></span>
        </div>
        {/* 数据点自查：自己稿子里的数据，对方会用同样的三连问你（观摩赛「64% 四口径」教训） */}
        {(() => {
          const pts = extractDataPoints(aiDraft || draft).slice(0, 6)
          if (!pts.length) return null
          return (
            <details className="draft-data-check">
              <summary className="muted">数据点自查：稿里有 {pts.length} 个数据点——经得起三连问吗？</summary>
              {pts.map((dp, i) => (
                <div className="split-block" key={i}>
                  <h4>{dp.raw}</h4>
                  <ul>{tripleProbe(dp).map((p, j) => <li key={j}>{p}</li>)}</ul>
                </div>
              ))}
            </details>
          )
        })()}
        {/* 赛前一页纸：把材料排成一页可打印的场上备忘（打印时只显示这一块） */}
        {(() => {
          const f = form
          const sideName = side === 'pro' ? '正方' : '反方'
          const hasAny = [f.def, f.std, f.a1, f.a2, f.val, f.quote].some((x) => x && x.trim())
          if (!hasAny) return null
          const dpts = extractDataPoints(aiDraft || draft).slice(0, 4)
          return (
            <details className="draft-onepager">
              <summary className="muted">赛前一页纸：把材料排成一张可打印的场上备忘</summary>
              <button
                className="btn-mini"
                style={{ margin: '6px 0' }}
                title="调起浏览器打印——打印时只输出这一页纸"
                onClick={() => window.print()}
              >
                打印这一页
              </button>
              <div className="onepager" id="onepager-sheet">
                <h2>赛前一页纸 · {topic || '(未填辩题)'}（{sideName}）</h2>
                {f.def && <p><b>定义：</b>{f.def}</p>}
                {f.std && <p><b>判准：</b>{f.std}</p>}
                {[f.a1, f.a2, f.a3].map((a, i) => a && a.trim() ? <p key={i}><b>论点 {i + 1}：</b>{a}</p> : null)}
                {f.quote && <p><b>金句 / 例证：</b>{f.quote}</p>}
                {f.val && <p><b>价值落点：</b>{f.val}</p>}
                {dpts.length > 0 && (
                  <>
                    <p><b>数据防守（对方敢报数就问）：</b></p>
                    <ul>{dpts.map((dp, i) => <li key={i}>{tripleProbe(dp).slice(0, 3).join('　')}</li>)}</ul>
                  </>
                )}
              </div>
            </details>
          )
        })()}
      </Section>
    </div>
  )
}

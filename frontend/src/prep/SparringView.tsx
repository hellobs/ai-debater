/** 人机对练（教学向一期）：你打一方，AI 打另一方，逐环节过招。
 *  与自动辩论共享后端 PER_STAGE 环节要求；每次回应 = 1 次上游调用，界面明示。
 *  一期不做胜负判定与评分——产品红线与自动辩论一致。 */
import { useEffect, useRef, useState } from 'react'
import { Section, downloadMd, useCopy } from './ui'
import { sparringStep, sparringReview } from '../api'
import { downloadDraftDocx } from './AutoDebateView'

interface SparringTurn {
  side: 'user' | 'ai'
  stage: string
  text: string
}

const STAGES = ['立论陈词', '驳论反驳', '质询与小结', '半场小结', '自由辩论', '结辩陈词']
const SIDE_LABEL = { pro: '正方', con: '反方' } as const

export function SparringView() {
  const [topic, setTopic] = useState('')
  const [userSide, setUserSide] = useState<'pro' | 'con'>('pro')
  const [stage, setStage] = useState('立论陈词')
  const [speech, setSpeech] = useState('')
  const [turns, setTurns] = useState<SparringTurn[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [copied, copyAll] = useCopy()
  /** 教练点评（1 次调用）：只评学员表现；与对打共用 busy 闸 */
  const [review, setReview] = useState('')
  const endRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns.length])

  const aiSide: 'pro' | 'con' = userSide === 'pro' ? 'con' : 'pro'
  // 自由辩论轮次：一来一回算一轮；半程（用户已说、AI 未回）也显示当前轮号
  const freeDone = turns.filter((t) => t.stage.startsWith('自由辩论')).length
  const freeRound = freeDone // 已完成轮数 = 条目数/2；下一条的自由辩论编号 = floor(条目/2)+1
  const stageFull = stage === '自由辩论' ? `自由辩论·${'一二三四五'[Math.min(4, Math.floor(freeRound / 2))]}轮` : stage

  const transcript = turns
    .map((t, i) => {
      const who = t.side === 'user' ? `你（${SIDE_LABEL[userSide]}）` : `AI（${SIDE_LABEL[aiSide]}）`
      return `${i + 1}. ${who}（${t.stage}）\n${t.text}`
    })
    .join('\n\n')

  const askAI = async (userSpeech: string) => {
    if (busy || !topic.trim()) return
    setBusy(true)
    setErr('')
    try {
      const data = await sparringStep({
        topic,
        user_side: userSide,
        stage: stageFull,
        history: turns.map((t) => ({ side: t.side, stage: t.stage, text: t.text })),
        user_speech: userSpeech,
      })
      if (data.ok && data.text) {
        setTurns((prev) => [...prev, { side: 'ai', stage: stageFull, text: data.text! }])
        setSpeech('')
      } else {
        setErr(data.error ?? '未知错误')
      }
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  const send = () => {
    if (!speech.trim()) return
    const mine: SparringTurn = { side: 'user', stage: stageFull, text: speech.trim() }
    setTurns((prev) => [...prev, mine])
    void askAI(mine.text)
  }

  const clear = () => {
    if (turns.length && !window.confirm('清空整场对练实录？不可恢复。')) return
    setTurns([])
    setErr('')
    setSpeech('')
    setReview('')
  }

  const askReview = async () => {
    if (busy || turns.length < 2) return
    setBusy(true)
    setErr('')
    try {
      const data = await sparringReview({
        topic,
        user_side: userSide,
        turns: turns.map((t) => ({ side: t.side, stage: t.stage, text: t.text })),
      })
      if (data.ok && data.text) setReview(data.text)
      else setErr(data.error ?? '未知错误')
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  const lastIsAi = turns.length > 0 && turns[turns.length - 1].side === 'ai'

  return (
    <div>
      <Section title="人机对练" tip="你打一方、AI 打另一方，逐环节过招。AI 的发言按该环节的标准要求生成——把它当陪练，不是判官">
        <input
          className="text-input"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="输入完整辩题，例：AI 生成内容应不应该强制标注"
        />
        <div className="prep-grid">
          <label>我打
            <select className="text-input" value={userSide} onChange={(e) => setUserSide(e.target.value as 'pro' | 'con')} disabled={busy || turns.length > 0}>
              <option value="pro">正方（AI 打反方）</option>
              <option value="con">反方（AI 打正方）</option>
            </select>
          </label>
        </div>
        <div className="model-chips">
          {STAGES.map((s) => (
            <button key={s} className={`chip${stage === s ? ' chip-on' : ''}`} onClick={() => setStage(s)} disabled={busy}>
              {s === '自由辩论' && freeRound > 0 ? `${s}·第${'一二三四五'[Math.min(4, Math.floor(freeRound / 2))]}轮` : s}
            </button>
          ))}
        </div>
        <textarea
          className="text-input"
          rows={3}
          value={speech}
          onChange={(e) => setSpeech(e.target.value)}
          placeholder={stage === '自由辩论' ? '你的短交锋（一两句，点破+推进）…' : `你的${stage}发言…`}
        />
        <div className="prep-actions">
          <button className="btn-mini" disabled={busy || !topic.trim() || !speech.trim()} onClick={send} title="先记下你的发言，AI 以对立持方回应；1 次上游调用">
            {busy ? 'AI 回应中…' : `说完了，听${SIDE_LABEL[aiSide]}回应（1 次调用）`}
          </button>
          {!lastIsAi && (
            <button className="btn-mini" disabled={busy || !topic.trim()} onClick={() => void askAI('')} title="不发言，直接让 AI 先开；1 次上游调用">
              让 AI 先手（1 次调用）
            </button>
          )}
          {turns.length > 0 && (
            <>
              <button className="btn-mini" onClick={() => copyAll(transcript)} title="复制整场实录">
                {copied ? '✓ 已复制' : '复制全文'}
              </button>
              <button className="btn-mini" onClick={() => downloadMd(`对练·${topic.trim() || '实录'}`, `# 人机对练实录：${topic.trim()}\n\n我方持方：${SIDE_LABEL[userSide]}\n\n${transcript}`)} title="下载 Markdown 实录（0 消耗）">
                下载 .md
              </button>
              <button
                className="btn-mini"
                disabled={busy || !topic.trim()}
                onClick={() => void downloadDraftDocx(`对练·${(topic.trim() || '实录').slice(0, 30).replace(/[/\\:*?"<>|]/g, '－')}`, transcript).catch((e) => setErr(`Word 导出失败：${String(e)}`))}
                title="下载 Word 实录（后端直出，0 消耗）"
              >
                下载 .docx
              </button>
              <button
                className="btn-mini"
                disabled={busy || turns.length < 2 || !topic.trim()}
                onClick={() => void askReview()}
                title="教练只评你的表现：最好的 / 被打穿的 / 环节规范 / 下场改一条；1 次上游调用"
              >
                {busy ? '生成中…' : review ? '重新点评（1 次调用）' : '教练点评本场（1 次调用）'}
              </button>
              <button className="btn-mini" onClick={clear} disabled={busy}>清空</button>
            </>
          )}
        </div>
        <p className="hint" style={{ color: 'var(--warn)' }}>成本：AI 每回应一次 = 1 次上游调用。环节要求与自动辩论同源（立论/驳论/质询/自由辩论/结辩）。</p>
        {err && <p className="error">{err}</p>}
      </Section>

      {turns.map((t, i) => (
        <div key={i} className={`prep-turn ${t.side === 'user' ? userSide : aiSide}`} title={`${t.side === 'user' ? '你' : 'AI'} · ${t.stage}`}>
          <div className="prep-turn-head">
            <span className="prep-turn-no">{i + 1}</span>
            <b>{t.side === 'user' ? `你（${SIDE_LABEL[userSide]}）` : `AI（${SIDE_LABEL[aiSide]}）`}</b>
            <span className="muted">{t.stage}</span>
          </div>
          <p className="prep-turn-text">{t.text}</p>
        </div>
      ))}
      {busy && <p className="muted" style={{ textAlign: 'center' }}>AI 正在准备回应…</p>}
      {review && (
        <section className="ledger debrief">
          <header className="ledger-head">
            <h3>教练点评</h3>
            <span className="ledger-meta">只评你的表现 · 引用原句说话</span>
            <button
              className="btn-mini"
              style={{ marginLeft: 'auto' }}
              onClick={() => { void navigator.clipboard?.writeText(review); }}
              title="复制点评全文"
            >
              复制
            </button>
          </header>
          <pre className="debrief-out">{review}</pre>
        </section>
      )}
      <div ref={endRef} />
    </div>
  )
}

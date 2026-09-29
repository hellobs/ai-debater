import { useRef, useState } from 'react'
import AdvisorColumn from './components/AdvisorColumn'
import LedgerPanel from './components/LedgerPanel'
import SettingsPanel from './components/SettingsPanel'
import { addCard, checkConsistency, deleteCard, fetchSession, patchCard, streamAnalyze } from './api'
import type {
  AdvisorResult,
  CardStatus,
  Conflict,
  LedgerCard,
  Rebuttal,
  SessionInfo,
} from './types'

/** 前端展示的参谋列（顺序与后端 advisors.yaml 一致） */
const COLUMNS = [
  { name: 'rebutter', label: '反驳手' },
  { name: 'questioner', label: '质询手' },
  { name: 'auditor', label: '逻辑审计员' },
]

const SAMPLE_TOPIC = 'AI 生成内容是否应享有著作权'
const SAMPLE_OPPONENT =
  '著作权法只保护自然人的智力成果，AI 不是人，所以 AI 生成内容不应享有著作权。'

export default function App() {
  const [topic, setTopic] = useState(SAMPLE_TOPIC)
  const [ourSide, setOurSide] = useState('控方（主张应享有）')
  const [opponentText, setOpponentText] = useState(SAMPLE_OPPONENT)

  const [results, setResults] = useState<Record<string, AdvisorResult>>({})
  const [running, setRunning] = useState(false)
  const [totalLatency, setTotalLatency] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const [sessionId, setSessionId] = useState<string | null>(null)
  const [ledger, setLedger] = useState<LedgerCard[]>([])
  const [conflicts, setConflicts] = useState<Conflict[]>([])
  const [adopting, setAdopting] = useState(false)

  const cancelRef = useRef<(() => void) | null>(null)
  const resultsRef = useRef<Record<string, AdvisorResult>>({})
  const sidRef = useRef<string | null>(null)

  const adoptedClaims = new Set(ledger.map((c) => c.claim.trim()))

  /** 从本轮结果里抽出反驳手的所有 claim，交给一致性检测 */
  const collectClaims = (): string[] => {
    const out: string[] = []
    for (const r of Object.values(resultsRef.current)) {
      if (r.kind === 'rebuttal' && Array.isArray(r.payload)) {
        for (const item of r.payload as Rebuttal[]) {
          if (item?.claim?.trim()) out.push(item.claim.trim())
        }
      }
    }
    return out
  }

  const handleSubmit = () => {
    if (running) return
    setResults({})
    setNotice(null)
    setTotalLatency(null)
    setConflicts([])
    setRunning(true)
    resultsRef.current = {}
    sidRef.current = sessionId

    cancelRef.current = streamAnalyze(
      { topic, our_side: ourSide, opponent_text: opponentText },
      sessionId,
      {
        onSession: (s: SessionInfo) => {
          sidRef.current = s.session_id
          setSessionId(s.session_id)
        },
        onResult: (r) => {
          resultsRef.current = { ...resultsRef.current, [r.advisor]: r }
          setResults((prev) => ({ ...prev, [r.advisor]: r }))
        },
        onDone: async (d) => {
          setRunning(false)
          setTotalLatency(d.latency_s)
          const sid = d.session_id || sidRef.current
          if (!sid) return
          setSessionId(sid)
          // 第二道闸：把新建议与台账比对，找出立场冲突
          const claims = collectClaims()
          if (claims.length) {
            try {
              setConflicts(await checkConsistency(sid, claims))
            } catch {
              /* 冲突检测失败不影响主流程 */
            }
          }
        },
        onError: (msg) => {
          setRunning(false)
          setNotice(msg)
        },
      },
    )
  }

  const handleReset = () => {
    cancelRef.current?.()
    cancelRef.current = null
    setResults({})
    setNotice(null)
    setTotalLatency(null)
    setConflicts([])
    setRunning(false)
  }

  const handleAdopt = async (r: Rebuttal) => {
    if (!sessionId || adopting) return
    setAdopting(true)
    try {
      const data = await addCard(sessionId, {
        claim: r.claim,
        major_premise: r.major_premise,
        minor_premise: r.minor_premise,
        conclusion: r.conclusion,
        source: 'rebutter',
      })
      setLedger(data.cards ?? [])
      // 采纳后原来的冲突可能已消解，重新核对一次
      const claims = collectClaims()
      if (claims.length) setConflicts(await checkConsistency(sessionId, claims))
    } catch (e) {
      setNotice(`采纳失败：${String(e)}`)
    } finally {
      setAdopting(false)
    }
  }

  const refreshLedger = async () => {
    if (!sessionId) return
    try {
      const snap = await fetchSession(sessionId)
      setLedger(snap.cards ?? [])
    } catch {
      /* 忽略 */
    }
  }

  const handleStatus = async (cardId: string, status: CardStatus) => {
    setAdopting(true)
    try {
      await patchCard(cardId, status)
      await refreshLedger()
    } finally {
      setAdopting(false)
    }
  }

  const handleDeleteCard = async (cardId: string) => {
    setAdopting(true)
    try {
      await deleteCard(cardId)
      await refreshLedger()
    } finally {
      setAdopting(false)
    }
  }

  const okCount = Object.values(results).filter((r) => r.status === 'ok').length

  return (
    <div className="app">
      <SettingsPanel
        topic={topic}
        ourSide={ourSide}
        opponentText={opponentText}
        running={running}
        sessionId={sessionId}
        onTopic={setTopic}
        onSide={setOurSide}
        onOpponent={setOpponentText}
        onSubmit={handleSubmit}
        onReset={handleReset}
      />

      <main className="board">
        <div className="board-bar">
          <span className="board-title">参谋建议</span>
          <span className="board-meta">
            {running
              ? `已返回 ${okCount} / ${COLUMNS.length} 路…`
              : totalLatency !== null
                ? `${COLUMNS.length} 路并行 · 总耗时 ${totalLatency}s`
                : '等待提交'}
          </span>
        </div>

        {notice && <div className="notice">{notice}</div>}

        <div className="columns">
          {COLUMNS.map((c) => (
            <AdvisorColumn
              key={c.name}
              label={c.label}
              result={results[c.name]}
              running={running}
              conflicts={conflicts}
              adopted={adoptedClaims}
              busy={adopting}
              onAdopt={c.name === 'rebutter' ? handleAdopt : undefined}
            />
          ))}
        </div>

        <LedgerPanel
          cards={ledger}
          conflicts={conflicts}
          busy={adopting}
          onStatus={handleStatus}
          onDelete={handleDeleteCard}
        />

        <p className="footnote">
          建议内容可直接点击修改。生成结果仅作参谋，最终判断与取舍在你。
        </p>
      </main>
    </div>
  )
}

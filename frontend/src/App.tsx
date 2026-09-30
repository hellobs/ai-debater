import { useCallback, useEffect, useRef, useState } from 'react'
import AdvisorColumn from './components/AdvisorColumn'
import CitationPanel from './components/CitationPanel'
import LedgerPanel from './components/LedgerPanel'
import MetricsPanel from './components/MetricsPanel'
import SettingsPanel from './components/SettingsPanel'
import {
  addCard,
  checkConsistency,
  deleteCard,
  deleteTopic,
  fetchHealth,
  fetchMetrics,
  fetchSession,
  fetchTopics,
  patchCard,
  saveTopic,
  streamAnalyze,
} from './api'
import type {
  AdvisorMeta,
  AdvisorResult,
  CardStatus,
  Conflict,
  DonePayload,
  HealthInfo,
  LedgerCard,
  MetricsInfo,
  Rebuttal,
  SessionInfo,
  StoredSuggestion,
  Topic,
} from './types'

export default function App() {
  // 辩题与立场：默认值来自辩题库（见 configs/topics.yaml），不是写死的常量
  const [topic, setTopic] = useState('')
  const [ourSide, setOurSide] = useState('正方')
  const [opponentText, setOpponentText] = useState('')

  const [health, setHealth] = useState<HealthInfo | null>(null)
  const [healthErr, setHealthErr] = useState<string | null>(null)
  const [topics, setTopics] = useState<Topic[]>([])
  const [selectedTopicId, setSelectedTopicId] = useState('')
  const [savingTopic, setSavingTopic] = useState(false)
  const [topicMsg, setTopicMsg] = useState('')

  const [results, setResults] = useState<Record<string, AdvisorResult>>({})
  const [running, setRunning] = useState(false)
  const [totalLatency, setTotalLatency] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const [sessionId, setSessionId] = useState<string | null>(null)
  const [ledger, setLedger] = useState<LedgerCard[]>([])
  const [conflicts, setConflicts] = useState<Conflict[]>([])
  const [adopting, setAdopting] = useState(false)
  const [budget, setBudget] = useState(12)
  const [metrics, setMetrics] = useState<MetricsInfo | null>(null)

  const cancelRef = useRef<(() => void) | null>(null)
  const resultsRef = useRef<Record<string, AdvisorResult>>({})
  const sidRef = useRef<string | null>(null)
  const bootstrappedRef = useRef(false)

  /** 参谋列由后端名册派生 —— 前端不再维护第二份，避免改了一处漏另一处。 */
  const columns: AdvisorMeta[] = health?.advisors ?? []

  const advisorLabels: Record<string, string> = Object.fromEntries(
    columns.map((c) => [c.name, c.label]),
  )

  const refreshMetrics = useCallback(async () => {
    try {
      setMetrics(await fetchMetrics())
    } catch {
      /* 仪表不可用不影响主流程 */
    }
  }, [])

  /** 健康状态归这里一份，SettingsPanel 只负责触发重查与显示。 */
  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await fetchHealth())
      setHealthErr(null)
    } catch (e) {
      setHealth(null)
      setHealthErr(String(e))
    }
  }, [])

  /** 用一条辩题填充输入区：立场与对方例句随辩题一起带出。 */
  const applyTopic = useCallback((t: Topic) => {
    setSelectedTopicId(t.id)
    setTopic(t.title)
    setOurSide(t.side_a)
    // 换辩题时旧的对方发言已不对题，用辩题自带的例句替换（没有则清空）
    setOpponentText(t.opponent_hint || '')
  }, [])

  const loadTopics = useCallback(async () => {
    try {
      const list = await fetchTopics()
      setTopics(list)
      // 只在首次加载时选中第一条，之后不覆盖用户的选择
      if (!bootstrappedRef.current && list.length) {
        bootstrappedRef.current = true
        applyTopic(list[0])
      }
    } catch (e) {
      setTopicMsg(`辩题库加载失败：${String(e)}`)
    }
  }, [applyTopic])

  useEffect(() => {
    void refreshHealth()
    void loadTopics()
    void refreshMetrics()
  }, [refreshHealth, loadTopics, refreshMetrics])

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

  const handleSelectTopic = (id: string) => {
    setTopicMsg('')
    if (!id) {
      // 切到「自定义」：保留当前文本，只是不再关联某条预设
      setSelectedTopicId('')
      return
    }
    const hit = topics.find((t) => t.id === id)
    if (hit) applyTopic(hit)
  }

  const handleSaveTopic = async () => {
    const title = topic.trim()
    if (!title || savingTopic) return
    setSavingTopic(true)
    setTopicMsg('')
    try {
      const cur = topics.find((t) => t.id === selectedTopicId)
      const otherSide = cur
        ? (ourSide === cur.side_a ? cur.side_b : cur.side_a)
        : '反方'
      const list = await saveTopic({
        title,
        side_a: ourSide.trim() || '正方',
        side_b: otherSide,
        opponent_hint: opponentText.trim(),
      })
      setTopics(list)
      const saved = list.find((t) => t.title === title && t.source === 'local')
      if (saved) setSelectedTopicId(saved.id)
      setTopicMsg(`已存为我的辩题：「${title}」（data/topics.json，不入仓）`)
    } catch (e) {
      setTopicMsg(`保存失败：${String(e)}`)
    } finally {
      setSavingTopic(false)
    }
  }

  const handleDeleteTopic = async () => {
    if (!selectedTopicId || savingTopic) return
    setSavingTopic(true)
    setTopicMsg('')
    try {
      const { ok, topics: list } = await deleteTopic(selectedTopicId)
      setTopics(list)
      setSelectedTopicId('')
      setTopicMsg(ok ? '已删除该本机辩题' : '预设辩题删不掉，只有「我的辩题」可以删')
    } catch (e) {
      setTopicMsg(`删除失败：${String(e)}`)
    } finally {
      setSavingTopic(false)
    }
  }

  const handleSubmit = () => {
    if (running || !columns.length) return
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
      budget,
      {
        onSession: (s: SessionInfo) => {
          sidRef.current = s.session_id
          setSessionId(s.session_id)
        },
        onResult: (r) => {
          resultsRef.current = { ...resultsRef.current, [r.advisor]: r }
          setResults((prev) => ({ ...prev, [r.advisor]: r }))
        },
        onDone: async (d: DonePayload) => {
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
          void refreshMetrics()
        },
        onError: async (msg) => {
          setRunning(false)
          const sid = sidRef.current
          let recovered = 0

          // 断线恢复：服务端是"算完一路就落库"，所以已算好的那几路能捞回来，
          // 不必重新花一次 token。只补当前 UI 里还缺的那几路。
          if (sid) {
            try {
              const snap = await fetchSession(sid)
              const latest: Record<string, StoredSuggestion> = {}
              for (const s of snap.suggestions ?? []) {
                if (!latest[s.advisor]) latest[s.advisor] = s
              }
              const patch: Record<string, AdvisorResult> = {}
              for (const c of columns) {
                if (resultsRef.current[c.name]) continue
                const s = latest[c.name]
                if (s && s.payload !== null && s.payload !== undefined) {
                  patch[c.name] = {
                    advisor: c.name,
                    label: c.label,
                    status: s.status === 'ok' ? 'ok' : (s.status as AdvisorResult['status']) ?? 'empty',
                    latency_s: s.latency_s ?? 0,
                    payload: s.payload,
                    raw: null,
                    error: null,
                    kind: c.kind,
                  }
                  recovered += 1
                }
              }
              if (recovered > 0) {
                resultsRef.current = { ...resultsRef.current, ...patch }
                setResults((prev) => ({ ...prev, ...patch }))
              }
            } catch {
              /* 恢复失败就只保留已收到的 */
            }
          }

          const got = Object.keys(resultsRef.current).length
          setNotice(
            `${msg}。已保留 ${got} / ${columns.length} 路结果` +
              (recovered > 0 ? `（其中 ${recovered} 路由服务端快照补齐）。` : '。') +
              ' 可点「生成参谋建议」重跑补齐。',
          )
          void refreshMetrics()
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
        budget={budget}
        health={health}
        healthErr={healthErr}
        onRecheck={refreshHealth}
        topics={topics}
        selectedTopicId={selectedTopicId}
        onSelectTopic={handleSelectTopic}
        onSaveTopic={handleSaveTopic}
        onDeleteTopic={handleDeleteTopic}
        saving={savingTopic}
        topicMsg={topicMsg}
        onTopic={setTopic}
        onSide={setOurSide}
        onOpponent={setOpponentText}
        onBudget={setBudget}
        onSubmit={handleSubmit}
        onReset={handleReset}
      />

      <main className="board">
        <div className="board-bar">
          <span className="board-title">参谋建议</span>
          <span className="board-bar-right">
            <span className="board-meta">
              {running
                ? `已返回 ${okCount} / ${columns.length} 路…`
                : totalLatency !== null
                  ? `${columns.length} 路并行 · 总耗时 ${totalLatency}s`
                  : '等待提交'}
            </span>
            <span className="export-bar">
              <a
                className={`btn-export${sessionId ? '' : ' disabled'}`}
                href={sessionId ? `/api/session/${sessionId}/export.md` : undefined}
                download
                aria-disabled={!sessionId}
                onClick={(e) => { if (!sessionId) e.preventDefault() }}
              >
                Markdown
              </a>
              <a
                className={`btn-export${sessionId ? '' : ' disabled'}`}
                href={sessionId ? `/api/session/${sessionId}/export.docx` : undefined}
                download
                aria-disabled={!sessionId}
                onClick={(e) => { if (!sessionId) e.preventDefault() }}
              >
                Word
              </a>
              <button
                className="btn-export"
                disabled={!sessionId}
                onClick={() => {
                  if (sessionId) window.open(`/api/session/${sessionId}/export.html`, '_blank')
                }}
              >
                PDF（打印）
              </button>
            </span>
          </span>
        </div>

        {notice && <div className="notice">{notice}</div>}

        {columns.length === 0 ? (
          <div className="notice">
            参谋团为空：后端未连通，或 <code>configs/advisors.yaml</code> 把所有参谋都停用了。
            请先启动后端，再把「服务状态」刷新一次。
          </div>
        ) : (
          <div className="columns">
            {columns.map((c) => (
              <AdvisorColumn
                key={c.name}
                label={c.label}
                domain={c.domain}
                result={results[c.name]}
                running={running}
                conflicts={conflicts}
                adopted={adoptedClaims}
                busy={adopting}
                onAdopt={c.kind === 'rebuttal' ? handleAdopt : undefined}
              />
            ))}
          </div>
        )}

        <LedgerPanel
          cards={ledger}
          conflicts={conflicts}
          busy={adopting}
          onStatus={handleStatus}
          onDelete={handleDeleteCard}
        />

        <MetricsPanel metrics={metrics} labels={advisorLabels} />

        {/* key 绑 sessionId：换会话时重置核验结果 */}
        <CitationPanel key={sessionId ?? 'none'} sessionId={sessionId} />

        <p className="footnote">
          建议内容可直接点击修改。生成结果仅作参谋，最终判断与取舍在你。
        </p>
      </main>
    </div>
  )
}

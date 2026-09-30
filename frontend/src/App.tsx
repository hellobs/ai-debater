import { useCallback, useEffect, useRef, useState } from 'react'
import AdvisorColumn from './components/AdvisorColumn'
import CitationPanel from './components/CitationPanel'
import LedgerPanel from './components/LedgerPanel'
import SettingsPanel from './components/SettingsPanel'
import {
  addCard,
  checkConsistency,
  deleteCard,
  deleteTopic,
  fetchHealth,
  fetchModels,
  fetchSession,
  fetchTopics,
  fetchUpstream,
  patchCard,
  saveTopic,
  // 改名：与下面的 `setUpstream`（state setter）撞名
  setUpstream as saveUpstream,
  streamAnalyze,
} from './api'
import { BUDGET_PRESETS } from './types'
import { findSaved, getLast, toPatch } from './upstreamStore'
import type {
  AdvisorMeta,
  AdvisorResult,
  CardStatus,
  Conflict,
  DonePayload,
  HealthInfo,
  LedgerCard,
  Rebuttal,
  SessionInfo,
  StoredSuggestion,
  Topic,
  UpstreamInfo,
  UpstreamPatch,
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
  /**
   * 时间预算。初值是占位；拿到 `/api/health` 后用后端的 `budget_s` 覆盖，
   * 用户一旦手动选过就不再动它（见 `budgetTouchedRef`）。
   *
   * 为什么不直接写 12：界面每次都会显式带 `budget_s`，前端写死就等于把后端
   * 的 `ADVISOR_BUDGET_S`（本地模型模式会设成 120）永远盖掉。
   */
  const [budget, setBudget] = useState(BUDGET_PRESETS[0].value)
  const budgetTouchedRef = useRef(false)

  // --- 上游与模型：模型名不再写死在前端，由后端探测后给 ---
  const [upstream, setUpstream] = useState<UpstreamInfo | null>(null)
  const [kinds, setKinds] = useState<string[]>([])
  const [models, setModels] = useState<string[]>([])
  const [modelsErr, setModelsErr] = useState('')
  /** 上面那份清单是从哪份配置探来的。没有它，改了形态还摆着旧清单就是误导。 */
  const [modelsFrom, setModelsFrom] = useState<{ kind: string; base_url: string } | null>(null)

  const refreshModels = useCallback(async (kind?: string, baseUrl?: string) => {
    try {
      const data = await fetchModels(kind, baseUrl)
      setModels(data.models ?? [])
      setModelsErr(data.error ?? '')
      setModelsFrom(
        data.models?.length
          ? { kind: data.kind, base_url: data.base_url }
          : null,
      )
    } catch (e) {
      setModels([])
      setModelsErr(String(e))
      setModelsFrom(null)
    }
  }, [])
  // 本轮实际生效的提示词包显示名（后端在 session 事件里回传）。
  // 没有它，用户只能靠猜"这次是按法学还是按通用在问"。
  const [packLabel, setPackLabel] = useState('')

  const cancelRef = useRef<(() => void) | null>(null)
  const resultsRef = useRef<Record<string, AdvisorResult>>({})
  const sidRef = useRef<string | null>(null)
  const bootstrappedRef = useRef(false)

  /** 参谋列由后端名册派生 —— 前端不再维护第二份，避免改了一处漏另一处。 */
  const columns: AdvisorMeta[] = health?.advisors ?? []

  /**
   * 当前选中辩题的领域。自由输入（没选预设辩题）时为空串，
   * 后端会落到默认提示词包。这里只搬运，不做 domain→包的判断。
   */
  const topicDomain = topics.find((t) => t.id === selectedTopicId)?.domain ?? ''

  const advisorLabels: Record<string, string> = Object.fromEntries(
    columns.map((c) => [c.name, c.label]),
  )

  /** 健康状态归这里一份，SettingsPanel 只负责触发重查与显示。 */
  const refreshHealth = useCallback(async () => {
    try {
      const h = await fetchHealth()
      setHealth(h)
      // 后端调宽了预算就该跟着宽 —— 用户手动选过之后不再覆盖（尊重显式选择）
      if (!budgetTouchedRef.current && h.budget_s != null) setBudget(h.budget_s)
      setHealthErr(null)
    } catch (e) {
      setHealth(null)
      setHealthErr(String(e))
    }
  }, [])

  /**
   * 切换上游。返回错误消息（成功返回 null）。
   *
   * 放在 `refreshHealth` 之后定义：切完要立刻重查健康（模型名变了）并重探模型清单
   * —— 探测只列清单，不产生推理调用，所以这里可以随手刷。
   */
  const applyUpstream = useCallback(async (patch: UpstreamPatch): Promise<string | null> => {
    try {
      setUpstream(await saveUpstream(patch))
      void refreshModels()
      void refreshHealth()
      return null
    } catch (e) {
      return String(e)
    }
  }, [refreshModels, refreshHealth])

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

  /** 上游状态 + 可用模型清单。两者都**不产生推理调用**，开机就能拿。 */
  const refreshUpstream = useCallback(async () => {
    try {
      const data = await fetchUpstream()
      setUpstream(data.upstream)
      setKinds(data.kinds ?? [])
    } catch {
      /* 后端没起时不干扰主流程 */
    }
  }, [])

  useEffect(() => {
    void refreshHealth()
    void loadTopics()
    void refreshUpstream()
    void refreshModels()
  }, [refreshHealth, loadTopics, refreshUpstream, refreshModels])

  /**
   * 开机自动应用**上次用过的那份配置** —— 后端进程重启后内存里的上游会清空，
   * 若没有这一步，配云端的人每次都要重填地址和密钥。
   *
   * 只跑一次，且失败（后端没起 / 那份配置已被删除）就静默跳过：
   * 自动恢复是便利，不该变成开机弹错。
   */
  useEffect(() => {
    const name = getLast()
    if (!name) return
    const cfg = findSaved(name)
    if (!cfg) return
    void (async () => {
      try {
        setUpstream(await saveUpstream(toPatch(cfg)))
        void refreshModels()
        void refreshUpstream()
        void refreshHealth()
      } catch {
        /* 后端没起：用户会在服务状态里看到，不必再弹一次 */
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 只在挂载时恢复一次
  }, [])

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
    setPackLabel('')
    resultsRef.current = {}
    sidRef.current = sessionId

    cancelRef.current = streamAnalyze(
      { topic, our_side: ourSide, opponent_text: opponentText, domain: topicDomain },
      sessionId,
      budget,
      {
        onSession: (s: SessionInfo) => {
          sidRef.current = s.session_id
          setSessionId(s.session_id)
          setPackLabel(s.pack_label ?? s.prompt_pack ?? '')
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
          // provider 的逐参谋 S/F/R 是后端进程里的实时计数器，重查才看得到
          void refreshHealth()
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
          void refreshHealth()
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
        advisorCount={columns.length}
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
        onBudget={(v) => {
          budgetTouchedRef.current = true
          setBudget(v)
        }}
        onSubmit={handleSubmit}
        onReset={handleReset}
        upstream={upstream}
        kinds={kinds}
        models={models}
        modelsErr={modelsErr}
        modelsFrom={modelsFrom}
        onApplyUpstream={applyUpstream}
        onRefreshModels={refreshModels}
      />

      <main className="board">
        <div className="board-bar">
          <span className="board-title">参谋建议</span>
          <span className="board-bar-right">
            {packLabel && (
              <span
                className="pack-tag"
                title="本轮参谋提示词用的是这个领域包，由辩题的「领域」决定"
              >
                提示词包 {packLabel}
              </span>
            )}
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

        {/* key 绑 sessionId：换会话时重置核验结果 */}
        <CitationPanel key={sessionId ?? 'none'} sessionId={sessionId} />

        <p className="footnote">
          建议内容可直接点击修改。生成结果仅作参谋，最终判断与取舍在你。
        </p>
      </main>
    </div>
  )
}

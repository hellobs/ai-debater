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
  fetchLatestCitations,
  fetchModels,
  fetchSession,
  fetchTopics,
  fetchUpstream,
  listSessions,
  patchCard,
  deleteSession,
  saveTopic,
  verifyCitations,
  // 改名：与下面的 `setUpstream`（state setter）撞名
  setUpstream as saveUpstream,
  streamAnalyze,
} from './api'
import { cardFor, isAdoptable } from './adopt'
import { citeBar, packNote } from './citeBar'
import { BUDGET_PRESETS } from './types'
import { loadLiveState, saveLiveState } from './liveStateStore'
import { findSaved, getLast, toPatch } from './upstreamStore'
import type {
  AdvisorMeta,
  AdvisorResult,
  AdoptCard,
  CardStatus,
  CitationReport,
  Conflict,
  DonePayload,
  HealthInfo,
  LedgerCard,
  SessionInfo,
  SessionRow,
  StoredSuggestion,
  Topic,
  UpstreamInfo,
  UpstreamPatch,
} from './types'

/** 台账会话列表取最近多少条。够用就行 —— 这列表是给"找一条删掉"用的，不是历史浏览器。 */
const SESSIONS_LIMIT = 20

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
  /** 本机台账里的会话清单（服务状态页里列出来，可逐条删）。纯本地 SQLite，不花上游调用。 */
  const [sessions, setSessions] = useState<SessionRow[]>([])
  const [sessionListErr, setSessionListErr] = useState('')
  /** 正在删哪一条（id），只用它来锁按钮，避免一次点出两个删除弹窗。 */
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null)
  const [ledger, setLedger] = useState<LedgerCard[]>([])
  const [conflicts, setConflicts] = useState<Conflict[]>([])
  /** 分析完成后自动核验的引用报告（UX-2）：语料已就位，核验不该等人来翻面板 */
  const [autoCite, setAutoCite] = useState<CitationReport | null>(null)
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
  /** 恢复完成后才允许写入 liveState —— 否则挂载时会把已存状态先用空值覆盖一遍 */
  const hydratedRef = useRef(false)

  /** 参谋列由后端名册派生 —— 前端不再维护第二份，避免改了一处漏另一处。 */
  const columns: AdvisorMeta[] = health?.advisors ?? []

  /**
   * 当前选中辩题的领域。自由输入（没选预设辩题）时为空串，
   * 后端会落到默认提示词包。这里只搬运，不做 domain→包的判断。
   */
  const topicDomain = topics.find((t) => t.id === selectedTopicId)?.domain ?? ''

  /**
   * 状态条上那两枚标签的文案。口径都在 `citeBar.ts`（可测），
   * 这里只算值 —— 显示逻辑散进 JSX 就没法测了。
   */
  const packTag = packNote(packLabel, topicDomain)
  const citeTag = citeBar(autoCite)

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

  /** 台账会话清单：开机拉一次、分析跑完再拉一次（中间可能冒出新会话）。 */
  const refreshSessions = useCallback(async () => {
    try {
      setSessions(await listSessions(SESSIONS_LIMIT))
      setSessionListErr('')
    } catch {
      // 后端没起：列表自然就是空的，服务状态页另有"后端未连通"那句说明
      setSessions([])
      setSessionListErr('')
    }
  }, [])

  useEffect(() => {
    void refreshHealth()
    void loadTopics()
    void refreshUpstream()
    void refreshModels()
    void refreshSessions()
  }, [refreshHealth, loadTopics, refreshUpstream, refreshModels, refreshSessions])

  /**
   * 删一条台账会话。后端在一个事务里级联清掉它的全部关联数据（见
   * `store.delete_session`），这里只负责把前端状态收干净。
   *
   * 删掉的正好是**当前会话**时必须一并清前端：否则界面还挂着一个后端已经不认识的
   * id，导出、一致性检测、引用核验都会去打一条 404。
   */
  const removeSession = useCallback(
    async (id: string) => {
      const row = sessions.find((s) => s.id === id)
      if (
        !window.confirm(
          `删除这条会话？它的对方发言、参谋卡与建议会一起删掉，不可恢复。\n\n` +
            `${row?.topic || '(无辩题)'} · ${row?.created_at ?? ''}`,
        )
      ) {
        return
      }
      setDeletingSessionId(id)
      try {
        const data = await deleteSession(id)
        if (!data.ok) {
          setNotice(`删除失败：后端没有那条会话（${id}）`)
          return
        }
        setSessions((prev) => prev.filter((s) => s.id !== id))
        if (id === sessionId) {
          setSessionId(null)
          setLedger([])
          setConflicts([])
          setAutoCite(null)
        }
        setNotice('已删除该会话及其全部记录')
      } catch (e) {
        setNotice(`删除会话失败：${String(e)}`)
      } finally {
        setDeletingSessionId(null)
        void refreshSessions()
      }
    },
    [sessions, sessionId],
  )

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

  /**
   * 现场状态恢复：刷新 / 误关标签页后把输入区原样拿回来。
   *
   * 对方发言不会再说第二遍，所以这些现场攒出来的文本必须活过一次 F5。
   * 会话本体在后端 SQLite 里一直都在——恢复 sessionId 就接回了台账与导出。
   * 恢复过就置 `bootstrappedRef`，阻止「默认选第一条辩题」把恢复值冲掉；
   * 用户手动调过预算的话也一并恢复（否则健康检查会覆盖它）。
   */
  useEffect(() => {
    const s = loadLiveState()
    // 空快照（辩题与发言都空）不值得恢复——它还带着副作用：抑制「默认选第一条
    // 辩题」的引导，会让辩题框卡死为空、提交永远禁用（体检第二轮实测咬到）。
    if (s && (s.topic || s.opponentText || s.sessionId)) {
      if (s.topic) {
        bootstrappedRef.current = true
        setTopic(s.topic)
        if (s.selectedTopicId) setSelectedTopicId(s.selectedTopicId)
      }
      if (s.ourSide) setOurSide(s.ourSide)
      if (s.opponentText) setOpponentText(s.opponentText)
      if (typeof s.budget === 'number' && s.budget > 0) {
        setBudget(s.budget)
        // 手选过的预算要标记，否则挂载后的健康检查会用服务端默认值覆盖它
        budgetTouchedRef.current = s.budgetTouched === true
      }
      if (s.sessionId) {
        setSessionId(s.sessionId)
        // 接回台账：会话快照在后端，重启后端也不丢
        void (async () => {
          try {
            const snap = await fetchSession(s.sessionId as string)
            setLedger(snap.cards ?? [])
          } catch {
            /* 后端没起：服务状态里看得见，恢复静默跳过 */
          }
        })()
      }
      // 参谋产出也一并还原 —— 体检发现的代价是「刷新一下要重花 5 次上游调用」。
      // 只收形状对得上的条目（status 是字符串）：后端或名册一改，旧 payload 可能已对不上，
      // 认不出来的那几路就空着（用户重跑一次即可），不拿旧结构去渲染。
      if (s.results && typeof s.results === 'object') {
        const back: Record<string, AdvisorResult> = {}
        for (const [name, r] of Object.entries(s.results)) {
          if (r && typeof r === 'object' && typeof (r as AdvisorResult).status === 'string') {
            back[name] = r as AdvisorResult
          }
        }
        if (Object.keys(back).length) {
          resultsRef.current = back
          setResults(back)
        }
      }
      if (typeof s.totalLatency === 'number') setTotalLatency(s.totalLatency)
    }
    hydratedRef.current = true
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 只在挂载时恢复一次
  }, [])

  /**
   * 现场状态落盘：任何一个字段变了就存。内容都很小，直写 localStorage 足够。
   * `results` 带进去是有意的 —— 点一次分析 = 5 次上游调用，刷新归零就得重花一遍
   * （理由见 `liveStateStore` 顶部）；写入端的体积上限在那里兜着。
   */
  useEffect(() => {
    if (!hydratedRef.current) return
    saveLiveState({
      topic,
      ourSide,
      opponentText,
      selectedTopicId,
      budget,
      sessionId,
      budgetTouched: budgetTouchedRef.current,
      results,
      totalLatency,
      savedAt: Date.now(),
    })
  }, [topic, ourSide, opponentText, selectedTopicId, budget, sessionId, results, totalLatency])

  const adoptedClaims = new Set(ledger.map((c) => c.claim.trim()))

  /**
   * 从本轮结果里抽出**所有可采纳参谋路**的主张，交给一致性检测。
   *
   * 采纳映射与界面上的「采纳」按钮同源（`adopt.cardFor`），所以"能采纳的"
   * 与"参与一致性检测的"永远是同一组，不会一边加了一边忘。
   */
  const collectClaims = (): string[] => {
    const out: string[] = []
    for (const r of Object.values(resultsRef.current)) {
      if (r.status !== 'ok' || !Array.isArray(r.payload)) continue
      for (const item of r.payload as unknown[]) {
        const card = cardFor(r.kind, item)
        if (card) out.push(card.claim)
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
    setAutoCite(null)
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
          // UX-2：自动核验本轮引用（纯本地，0 消耗）。失败不打扰——
          // 面板里仍有手动「核验本轮引用」可重试。
          try {
            setAutoCite(await verifyCitations(sid))
          } catch {
            /* 核验失败静默，面板可手动重跑 */
          }
          // provider 的逐参谋 S/F/R 是后端进程里的实时计数器，重查才看得到
          void refreshHealth()
          // 这一轮可能新建了会话，台账列表要跟着更新
          void refreshSessions()
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
    setAutoCite(null)   // 引用状态条也要跟着清，否则残留已清空那一轮的核验信息
    setRunning(false)
  }

  const handleAdopt = async (card: AdoptCard) => {
    if (!sessionId || adopting) return
    setAdopting(true)
    try {
      const data = await addCard(sessionId, card)
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
        sessions={sessions}
        sessionListErr={sessionListErr}
        deletingSessionId={deletingSessionId}
        onRefreshSessions={() => void refreshSessions()}
        onDeleteSession={(id) => void removeSession(id)}
      />

      <main className="board">
        <div className="board-bar">
          <span className="board-title">参谋建议</span>
          <span className="board-bar-right">
            {packTag.text && (
              <span className="pack-tag" title={packTag.title}>
                {packTag.text}
              </span>
            )}
            {citeTag && (
              <span
                className={`pack-tag${citeTag.warn ? ' cite-warn' : ''}`}
                title={citeTag.title}
              >
                {citeTag.text}
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
                title="下载 Markdown 复盘（后端直接生成，不受浏览器版本影响）"
                onClick={(e) => { if (!sessionId) e.preventDefault() }}
              >
                Markdown
              </a>
              <a
                className={`btn-export${sessionId ? '' : ' disabled'}`}
                href={sessionId ? `/api/session/${sessionId}/export.docx` : undefined}
                download
                aria-disabled={!sessionId}
                title="下载 Word 复盘（后端直接生成，不受浏览器版本影响）"
                onClick={(e) => { if (!sessionId) e.preventDefault() }}
              >
                Word
              </a>
              <button
                className="btn-export"
                disabled={!sessionId}
                title="打开打印优化页，在浏览器里选「打印 → 另存为 PDF」。需较新的浏览器（Chrome / Edge / Firefox 现代版本）；旧内核可能排版异常。"
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
                onAdopt={isAdoptable(c.kind) ? handleAdopt : undefined}
                sessionId={sessionId}
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
        <CitationPanel
          key={sessionId ?? 'none'}
          sessionId={sessionId}
          autoReport={autoCite}
        />

        <p className="footnote">
          建议可直接点击修改，是否采纳由你判断。PDF 在打印页另存（需较新浏览器）；Word / Markdown 直接下载。
        </p>
      </main>
    </div>
  )
}

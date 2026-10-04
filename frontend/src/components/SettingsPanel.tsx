import { useEffect, useState } from 'react'
import { knowledgeStatus, uploadKnowledge } from '../api'
import { useRecorder } from '../useRecorder'
import {
  BUDGET_PRESETS,
  type HealthInfo,
  type SessionRow,
  type Topic,
  type UpstreamInfo,
  type UpstreamPatch,
} from '../types'
import {
  clearAll,
  findSaved,
  getLast,
  loadSaved,
  removeConfig,
  saveConfig,
  type SavedUpstream,
} from '../upstreamStore'

/** 形态 → 界面说法。kind 是协议层面的名字，用户关心的是"连什么、要不要钱"。 */
const KIND_LABELS: Record<string, string> = {
  ollama: '本机 Ollama（免密钥，本地推理）',
  openai: 'OpenAI 兼容端点（云端 / 自建）',
  anthropic: 'Anthropic 协议网关（经内置协议桥转译）',
}

/**
 * 各形态的默认地址。**切换形态时必须跟着换**，否则会残留上一个形态的地址 ——
 * 症状是"选了 OpenAI 却还连着本机 Ollama"，而且因为 Ollama 恰好兼容 OpenAI
 * 协议，探测和应用全都成功，用户只会觉得"配置怎么不生效"。
 */
const DEFAULT_BASE_URL: Record<string, string> = {
  ollama: 'http://127.0.0.1:11434/v1',
  openai: '',
  anthropic: '',
}

/** 「本机 Ollama · 127.0.0.1:11434」—— 说清一份清单来自哪个端点，不带路径。 */
function sourceLabel(from: { kind: string; base_url: string }): string {
  const host = from.base_url.split('//').pop()?.split('/')[0] ?? from.base_url
  return `${KIND_LABELS[from.kind] ?? from.kind} · ${host}`
}

const PLACEHOLDERS: Record<string, string> = {
  ollama: 'http://127.0.0.1:11434/v1',
  openai: 'https://api.example.com/v1',
  anthropic: 'https://gateway.example.com',
}

/** 是不是在本机 Ollama 的地址上 —— 它兼容 OpenAI 协议，通用形态连它也算对，
 *  但用户看到"本地模型"出现在 OpenAI 形态下会以为是配置错了。 */
function isLocalOllamaUrl(url: string): boolean {
  return /(127\.0\.0\.1|localhost|\[::1\]):11434/.test(url)
}

/** 按 domain 分组，保持后端返回顺序（= 配置顺序）。 */
function groupByDomain(topics: Topic[]): [string, Topic[]][] {
  const groups: [string, Topic[]][] = []
  for (const t of topics) {
    const hit = groups.find(([d]) => d === t.domain)
    if (hit) hit[1].push(t)
    else groups.push([t.domain, [t]])
  }
  return groups
}

export default function SettingsPanel(props: {
  topic: string
  ourSide: string
  opponentText: string
  running: boolean
  /** 生效的参谋路数。为 0 时提交必然空转，所以按钮直接禁用并把原因说清。 */
  advisorCount: number
  sessionId: string | null
  budget: number
  health: HealthInfo | null
  healthErr: string | null
  onRecheck: () => Promise<void>
  topics: Topic[]
  selectedTopicId: string
  onSelectTopic: (id: string) => void
  onSaveTopic: () => void
  onDeleteTopic: () => void
  saving: boolean
  /** 辩题库操作的回执（保存/删除），只在左侧面板就近显示 */
  topicMsg: string
  onTopic: (v: string) => void
  onSide: (v: string) => void
  onOpponent: (v: string) => void
  onBudget: (v: number) => void
  onSubmit: () => void
  onReset: () => void
  // --- 上游与模型（运行时可改） ---
  /** 当前生效的上游（脱敏）。null = 还没拿到后端状态。 */
  upstream: UpstreamInfo | null
  kinds: string[]
  models: string[]
  modelsErr: string
  /** 清单来源配置。与表单当前值不一致 = 清单过期，不该再摆出来。 */
  modelsFrom: { kind: string; base_url: string } | null
  /** 应用改动。返回错误消息（成功返回 null）。 */
  onApplyUpstream: (patch: UpstreamPatch) => Promise<string | null>
  /** 探测模型列表（用当前填的 kind / 地址，不必先应用）。 */
  onRefreshModels: (kind: string, baseUrl: string) => Promise<void>
  // --- 本机台账会话（以前只能增、不能删，见 decision-log 续七） ---
  /** `/api/sessions` 给的最近若干条。 */
  sessions: SessionRow[]
  /** 列表拉取失败原因（后端没起时为空串——那时候整页已经有别的报错了）。 */
  sessionListErr: string
  /** 正在删哪条（id）。只用来锁按钮，别拿它判断"能不能删"。 */
  deletingSessionId: string | null
  onRefreshSessions: () => void
  onDeleteSession: (id: string) => void
}) {
  const {
    topic, ourSide, opponentText, running, advisorCount, sessionId, budget,
    health, healthErr, onRecheck,
    topics, selectedTopicId, onSelectTopic, onSaveTopic, onDeleteTopic, saving,
    topicMsg,
    onTopic, onSide, onOpponent, onBudget, onSubmit, onReset,
    upstream, kinds, models, modelsErr, modelsFrom, onApplyUpstream, onRefreshModels,
    sessions, sessionListErr, deletingSessionId, onRefreshSessions, onDeleteSession,
  } = props

  const [checking, setChecking] = useState(false)

  // ---- 左栏 Menu 分区 ----
  // 现场高频的输入（辩题/立场/对方发言/预算）与低频配置（模型、服务状态）分栏，
  // 全部竖排会把现场要用的输入顶出首屏。表单状态都声明在组件顶层（不在这三个
  // 条件分支里），切来切去不丢内容。
  const [tab, setTab] = useState<'live' | 'model' | 'status'>('live')

  // ---- 语音收音（阶段 7 一期：手动分闸——对方开口点开始，说完点结束） ----
  const rec = useRecorder()
  const [asrMsg, setAsrMsg] = useState('')
  /** 参考知识库（通用辩题素材）：上传即生效，注入参谋上下文的【参考知识】段 */
  const [kb, setKb] = useState<{ files: number; chunks: number } | null>(null)
  const [kbMsg, setKbMsg] = useState('')
  /** 流式模型就绪才亮按钮；后端没连上/版本旧一律按不可用处理 */
  const streamReady = health?.asr?.stream === true

  const startRec = async () => {
    setAsrMsg('')
    await rec.start()
  }

  /** 停止 → 全文**追加**进输入框。转写已随收音实时完成，无需再上传。
   *  仍不自动触发分析：识别错字要人核对，「以什么文本去问参谋」决策权在人。 */
  const stopRec = async () => {
    const result = await rec.stop()
    if (!result) return
    if (result.text) {
      onOpponent((opponentText ? opponentText.trimEnd() + "\n" : "") + result.text)
      setAsrMsg(
        `已收音 ${Math.floor(rec.elapsed)}s、转出 ${result.text.length} 字，请核对后再生成建议`,
      )
    }
  }

  // ---- 上游表单 ----
  // 初值来自后端；后端那边的值真变了（切换成功）才回填，避免每帧覆盖用户正在输入的内容。
  const [kind, setKind] = useState(upstream?.kind ?? 'ollama')
  const [baseUrl, setBaseUrl] = useState(upstream?.base_url ?? '')
  const [model, setModel] = useState(upstream?.model ?? '')
  /** 密钥**永不回填**（后端也不回传明文）。留空 = 沿用已有的那把。 */
  const [apiKey, setApiKey] = useState('')
  const [applying, setApplying] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  // ---- 本机保存的多份配置 ----
  const [saved, setSaved] = useState<SavedUpstream[]>(() => loadSaved())
  /** 当前挂着哪一份（空 = 还没存过）。初值取"上次用过的那份"，
   *  这样开机自动恢复之后，界面上「删除」才知道删的是谁。 */
  const [savedName, setSavedName] = useState(() => getLast() ?? '')
  const [nameDraft, setNameDraft] = useState(() => getLast() ?? '')
  /** 这份已保存配置里有一把密钥（不回显，只提示"已保存"）。 */
  const [hasStoredKey, setHasStoredKey] = useState(false)
  /**
   * 「记住密钥到本机」勾选。**默认不勾** —— 明文密钥躺进浏览器 localStorage
   * 该是一次显式决定，不该由顺手点「保存」带来（upstreamStore 文件头有同样说明）。
   * 勾选只影响**保存**那一档；「应用」始终会带上这把（填了就用填的）。
   */
  const [rememberKey, setRememberKey] = useState(false)

  /** 清单是不是从"当前表单里这份配置"探来的。 */
  const staleModels = Boolean(
    modelsFrom && (modelsFrom.kind !== kind || modelsFrom.base_url !== baseUrl),
  )
  const [upstreamMsg, setUpstreamMsg] = useState<string | null>(null)

  useEffect(() => {
    void knowledgeStatus().then(setKb).catch(() => { /* 后端未连时静默 */ })
  }, [])

  useEffect(() => {
    if (!upstream) return
    setKind(upstream.kind)
    setBaseUrl(upstream.base_url)
    setModel(upstream.model)
    // 只依赖三个具体值：upstream 每次请求都是新对象，整个对象进依赖会一直重置输入
  }, [upstream?.kind, upstream?.base_url, upstream?.model])

  const refresh = async () => {
    setRefreshing(true)
    await onRefreshModels(kind, baseUrl)
    setRefreshing(false)
  }

  /** 换形态 = 换一种上游：地址换成新形态的默认值，模型作废重选。
   *  模型名属于端点，带着走只会填出一个新端点根本没有的模型。 */
  const switchKind = (next: string) => {
    setKind(next)
    setBaseUrl(DEFAULT_BASE_URL[next] ?? '')
    setModel('')
  }

  /** 没起名时给个认得出的默认名（形态 + 主机），免得两份配置都叫"未命名"。 */
  const suggestName = () => {
    const host = baseUrl.split('//').pop()?.split('/')[0] || '本机'
    const label = (KIND_LABELS[kind] ?? kind).split('（')[0]
    return `${label} · ${host}`
  }

  /** 载入一份已保存的配置：**密钥不回填**（只标记"已保存一把"）。
   *  选完立刻应用 —— 用户要的是"点一下就能用"，不是"填完再点一次应用"。 */
  const loadConfig = async (name: string) => {
    const cfg = findSaved(name)
    if (!cfg) return
    setSavedName(name)
    setNameDraft(name)
    setKind(cfg.kind)
    setBaseUrl(cfg.base_url)
    setModel(cfg.model)
    setApiKey('')
    setHasStoredKey(Boolean(cfg.api_key))
    setApplying(true)
    setUpstreamMsg(null)
    // 空密钥同样**不提交**（后端 `api_key=None` 才是"不动"，传 '' 是清空）：
    // 载入一份没记住密钥的配置，不该顺手把后端内存里那把也洗掉
    const patch: UpstreamPatch = { kind: cfg.kind, base_url: cfg.base_url, model: cfg.model }
    if (cfg.api_key) patch.api_key = cfg.api_key
    const err = await onApplyUpstream(patch)
    setApplying(false)
    setUpstreamMsg(err ?? `已载入「${name}」`)
  }

  /**
   * 存一份（同名覆盖）。
   *
   * 密钥怎么进这条记录，全看勾没勾「记住密钥」：
   * - 没勾（默认）→ **根本不提交密钥字段**，这条记录存下来不带密钥；
   * - 勾了且输入框有值 → 存这把（明文，见 upstreamStore 文件头）；
   * - 勾了但没重填 → 沿用这份已有的那把（改个模型不该把密钥洗掉）。
   */
  const persist = () => {
    const name = nameDraft.trim() || suggestName()
    const key = rememberKey ? apiKey.trim() : undefined
    setSaved(
      saveConfig({
        name,
        kind,
        base_url: baseUrl,
        model,
        api_key: key,
        remember_key: rememberKey,
      }),
    )
    setSavedName(name)
    setNameDraft(name)
    setHasStoredKey(Boolean(key))
    setUpstreamMsg(
      rememberKey && key
        ? `已保存到本机：${name}（含密钥）`
        : `已保存到本机：${name}${rememberKey ? '（密钥留空，沿用已保存的那把）' : '（不存密钥）'}`,
    )
  }

  const forget = () => {
    if (!savedName) return
    setSaved(removeConfig(savedName))
    setSavedName('')
    setNameDraft('')
    setHasStoredKey(false)
    setUpstreamMsg(`已删除「${savedName}」及其密钥`)
  }

  /** 清空本机保存的**全部**配置 —— 换机器 / 借电脑时用。
   *  它是破坏性的（密钥拿不回来），所以要一次确认。 */
  const forgetAll = () => {
    const n = saved.length
    if (!n) return
    if (!window.confirm(`将清除本机保存的 ${n} 份配置及其密钥（不可恢复）。继续？`)) return
    setSaved(clearAll())
    setSavedName('')
    setNameDraft('')
    setHasStoredKey(false)
    setUpstreamMsg(`已清除本机保存的 ${n} 份配置及其密钥`)
  }

  const applyUpstream = async () => {
    // openai / anthropic 没有地址就应用，等于把上游指到一个空串 —— 拦在本地说清
    if (kind !== 'ollama' && !baseUrl.trim()) {
      setUpstreamMsg('先填端点地址，再应用。')
      return
    }
    setApplying(true)
    setUpstreamMsg(null)
    const patch: UpstreamPatch = { kind, base_url: baseUrl, model }
    if (kind === 'ollama') {
      // 本机推理不需要密钥：显式清空，免得上一把（切形态前填的）留在后端内存里
      patch.api_key = ''
    } else if (apiKey.trim()) {
      patch.api_key = apiKey.trim()
    } else if (hasStoredKey && savedName) {
      // 没重填就用这份已存的那个 —— 否则每次"应用"都会把密钥洗成空
      const stored = findSaved(savedName)?.api_key ?? ''
      if (stored) patch.api_key = stored
    }
    const err = await onApplyUpstream(patch)
    setApiKey('')
    setUpstreamMsg(err ?? `已切换：${KIND_LABELS[kind] ?? kind} · ${model || '(未指定模型)'}`)
    setApplying(false)
  }

  const uploadKb = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    setKbMsg('')
    try {
      const data = await uploadKnowledge(f.name.replace(/\.(txt|md)$/i, ''), await f.text())
      if (data.ok) {
        setKb(await knowledgeStatus())
        setKbMsg(`已导入「${f.name}」，知识库共 ${data.chunks} 块`)
      } else {
        setKbMsg(`导入失败：${data.error ?? '未知原因'}`)
      }
    } catch (err) {
      setKbMsg(`导入请求失败：${String(err)}`)
    } finally {
      e.target.value = ''
    }
  }

  /** 名册被全部停用时，提交不会发出任何请求 —— 按钮必须禁用并说明原因，
   *  否则点击看起来毫无反应（此前就是这个问题）。 */
  const noAdvisors = advisorCount === 0

  /** 后端默认可能不在预设里（本地模型的 120s、或自定义的 45s）。补一项再渲染，
   *  否则 `<select>` 会因为没有匹配项而显示空白，看着像"没选上"。 */
  const budgetOptions = BUDGET_PRESETS.some((b) => b.value === budget)
    ? BUDGET_PRESETS
    : [{ label: `服务端默认 ${budget}s`, value: budget }, ...BUDGET_PRESETS]

  /** 健康状态归父级一份（App 还要用它渲染参谋列），这里只负责触发与按钮态。 */
  const check = async () => {
    setChecking(true)
    try {
      await onRecheck()
    } finally {
      setChecking(false)
    }
  }

  const selected = topics.find((t) => t.id === selectedTopicId) ?? null
  const groups = groupByDomain(topics)

  // 立场选项由辩题带出；若当前值不在其中（自定义过），额外补一项，避免下拉吞掉它
  const sideOptions = selected ? [selected.side_a, selected.side_b] : ['正方', '反方']
  const sides = ourSide && !sideOptions.includes(ourSide)
    ? [...sideOptions, ourSide]
    : sideOptions

  return (
    <aside className="panel">
      <h1 className="brand">{health?.brand ?? '辩手参谋台'}</h1>
      <p className="brand-sub">多 Agent 并行给你出主意，用不用由你判断</p>

      <nav className="menu-tabs" role="tablist" aria-label="设置分区">
        {([['live', '现场输入'], ['model', '模型与上游'], ['status', '服务状态']] as const).map(
          ([key, label]) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              className={tab === key ? 'on' : ''}
              onClick={() => setTab(key)}
            >
              {label}
              {key === 'status' && healthErr && <span className="dot">!</span>}
            </button>
          ),
        )}
      </nav>

      {tab === 'live' && (<>
      <label className="block">
        <span className="block-label">① 辩题</span>
        <select
          className="text-input"
          value={selectedTopicId}
          onChange={(e) => onSelectTopic(e.target.value)}
        >
          <option value="">— 自定义辩题（在下面直接写）—</option>
          {groups.map(([domain, items]) => (
            <optgroup key={domain} label={domain}>
              {items.map((t) => (
                <option key={t.id} value={t.id}>{t.title}</option>
              ))}
            </optgroup>
          ))}
        </select>
        <input
          className="text-input spaced"
          value={topic}
          onChange={(e) => onTopic(e.target.value)}
          placeholder="例：AI 生成内容是否应享有著作权"
        />
        <span className="row-actions">
          <button
            className="btn-inline"
            onClick={onSaveTopic}
            disabled={saving || !topic.trim()}
            title="把当前辩题、我方立场与对方例句一起存进 data/topics.json（不入仓）"
          >
            保存为我的辩题
          </button>
          {selected?.source === 'local' && (
            <button
              className="btn-inline danger"
              onClick={onDeleteTopic}
              disabled={saving}
              title="只删得掉本机自建的那份，入仓预设删不动"
            >
              删除
            </button>
          )}
        </span>
        <span className="hint">
          {selected?.note
            ? `争点：${selected.note}`
            : '选定辩题会自动带出立场与对方例句。'}
        </span>
        {topicMsg && <span className="topic-msg">{topicMsg}</span>}
      </label>

      <label className="block">
        <span className="block-label">② 我方立场</span>
        <select
          className="text-input"
          value={ourSide}
          onChange={(e) => onSide(e.target.value)}
        >
          {sides.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </label>

      <label className="block">
        <span className="block-label">③ 对方刚说的话</span>
        <textarea
          className="text-input"
          rows={6}
          value={opponentText}
          onChange={(e) => onOpponent(e.target.value)}
          placeholder="手打，或点下方「流式收音」边说边出字"
        />
        <div className="asr-row">
          {rec.listening || rec.stopping ? (
            <button
              className="btn-mini danger asr-rec"
              onClick={() => void stopRec()}
              disabled={rec.stopping}
            >
              <span className="rec-dot" aria-hidden />
              {rec.stopping ? '收尾中…' : `结束收音（${Math.floor(rec.elapsed)}s / 600s）`}
            </button>
          ) : (
            <button
              className="btn-mini"
              onClick={() => void startRec()}
              disabled={!streamReady}
              title={
                streamReady
                  ? '手动分闸：对方开口时点这里，说完点「结束收音」。收音期间文字实时出现'
                  : (health?.asr?.stream === false
                    ? '流式模型未下载：先运行 bash scripts/fetch_asr_model.sh'
                    : (health?.asr?.reason ?? '后端未连通，无法收音'))
              }
            >
              🎙 流式收音（边说边出字）
            </button>
          )}
          {rec.listening && (
            <span className="asr-level" aria-hidden>
              <span style={{ width: `${Math.min(100, rec.level * 100)}%` }} />
            </span>
          )}
        </div>
        {(rec.listening || rec.stopping) && (
          <div className="asr-live" aria-live="polite">
            {rec.liveText || '正在听……说出的内容会实时出现在这里'}
          </div>
        )}
        {asrMsg && <span className="hint">{asrMsg}</span>}
        {rec.error && <span className="warn-block" style={{ display: 'block', marginTop: 6 }}>{rec.error}</span>}
        {!streamReady && !rec.error && (
          <span className="hint">
            语音未启用：{health
              ? (health.asr?.stream === false
                ? '未下载模型（fetch_asr_model.sh）'
                : (health.asr?.reason ?? '后端版本较旧'))
              : '后端未连通'}。手打不受影响。
          </span>
        )}
      </label>

      <label className="block">
        <span className="block-label">④ 时间预算</span>
        <select
          className="text-input"
          value={budget}
          onChange={(e) => onBudget(Number(e.target.value))}
        >
          {budgetOptions.map((b) => (
            <option key={b.value} value={b.value}>{b.label}</option>
          ))}
        </select>
        {/* 现场档（12/20s）是按云端响应速度定的。本地模型下单路就可能跑不完，
            会被整片判成「超时」—— 那不是模型不行，是档位不匹配。这里就地说明，
            免得再去翻本地模型报告。 */}
        {budget > 0 && budget < 30 && (
          <p className="warn-block" style={{ marginTop: 6 }}>
            上游较慢时多数参谋会超时——建议改选 120s 或「不限」。
          </p>
        )}
        <span className="hint">
          到点未返回的参谋标「超时」并立刻交付，不阻塞其余。
        </span>
      </label>
      </>)}

      {tab === 'model' && (
      <div className="block">
        <span className="block-label">⑤ 模型与上游</span>
        {/* 上游只驻留后端内存：后端一重启就回到 .env 的初值（通常是云端网关）。
            不就地说明的话，用户重启后顺手点一次分析，就用云端额度跑了本该本地的活。 */}
        <p className="warn-block" style={{ marginTop: 6 }}>
          上游只驻留后端内存，重启后端会回到 <code>.env</code> 的初值 —— 用前请先在这里确认一次。
        </p>

        {/* 配过一次就该一直能用：多份配置存在本机浏览器，选一份即载入并应用 */}
        <div className="model-row">
          <select
            className="text-input"
            value={savedName}
            onChange={(e) => void loadConfig(e.target.value)}
          >
            <option value="">{saved.length ? '— 选择已保存的配置 —' : '— 还没有保存过 —'}</option>
            {saved.map((c) => (
              <option key={c.name} value={c.name}>{c.name}</option>
            ))}
          </select>
          <button className="btn-mini" onClick={forget} disabled={!savedName}>
            删除
          </button>
          <button
            className="btn-mini danger"
            onClick={forgetAll}
            disabled={!saved.length}
            title="清除本机保存的全部配置与密钥（不含后端内存里的那把）"
          >
            清除全部
          </button>
        </div>

        <select
          className="text-input"
          style={{ marginTop: 6 }}
          value={kind}
          onChange={(e) => switchKind(e.target.value)}
        >
          {(kinds.length ? kinds : ['ollama', 'openai', 'anthropic']).map((k) => (
            <option key={k} value={k}>{KIND_LABELS[k] ?? k}</option>
          ))}
        </select>

        <input
          className="text-input"
          style={{ marginTop: 6 }}
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder={PLACEHOLDERS[kind] ?? '端点地址'}
        />

        {/* 「OpenAI 兼容端点」连本机 Ollama 完全合法（Ollama 本来就讲 OpenAI 协议），
            所以探测/应用都会成功 —— 但正因为全都成功，用户只会觉得
            "选了 OpenAI 怎么还有本地模型"。就地说明，把困惑变成明示。 */}
        {kind === 'openai' && isLocalOllamaUrl(baseUrl) && (
          <p className="hint">
            这是本机 Ollama：两者同一端点，选「本机 Ollama」更省事。
          </p>
        )}

        {/* anthropic 形态下这个地址是**上游网关**，mavis 并不直连它（走内置协议桥转译）。
            不说明的话，填错协议就会变成"连上了但一直 404"，很难定位。 */}
        {kind === 'anthropic' && (
          <span className="hint">
            经内置协议桥转译后访问。
          </span>
        )}

        {/* 本机 Ollama 不需要密钥 —— 摆一个禁用输入框只是占位噪音。
            切回 ollama 时还要把后端内存里那把旧密钥清掉（见 applyUpstream）。 */}
        {kind !== 'ollama' && (
          <>
            <input
              className="text-input"
              style={{ marginTop: 6 }}
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={
                hasStoredKey ? '已在本机保存一把密钥，留空即沿用它' : 'API key'
              }
            />
            {/* 默认不勾：把明文密钥写进浏览器是一次显式决定。勾了也不加密 ——
                只不往 localStorage 里塞（见 upstreamStore 文件头）。 */}
            <label className="check-row" style={{ marginTop: 6 }}>
              <input
                type="checkbox"
                checked={rememberKey}
                onChange={(e) => setRememberKey(e.target.checked)}
              />
              <span>
                记住密钥到本机（明文存浏览器，清掉需「清除全部」）
                {rememberKey && hasStoredKey && (
                  <span className="muted"> · 留空即沿用已保存的那把</span>
                )}
                {!rememberKey && hasStoredKey && (
                  <span className="muted"> · 当前这份已保存的密钥会被清掉</span>
                )}
              </span>
            </label>
          </>
        )}

        <div className="model-row">
          <input
            className="text-input"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="模型名（可手填）"
          />
          <button
            className="btn-mini"
            onClick={() => void refresh()}
            disabled={refreshing || !baseUrl.trim()}
            title={baseUrl.trim() ? undefined : '先填端点地址'}
          >
            {refreshing ? '探测中…' : '探测'}
          </button>
        </div>

        {/* 清单只在它确实属于**当前这份配置**时才摆出来。改了形态或地址还没重探，
            旧清单就是误导 —— 照着点会填一个这个端点根本没有的模型名。 */}
        {models.length > 0 && modelsFrom && staleModels ? (
          <p className="hint" style={{ marginTop: 6 }}>
            清单属于另一份配置（{sourceLabel(modelsFrom)}），需重新「探测」。
          </p>
        ) : models.length > 0 ? (
          <div className="model-chips">
            {models.map((m) => (
              <button
                key={m}
                className={m === model ? 'chip chip-on' : 'chip'}
                onClick={() => setModel(m)}
              >
                {m}
              </button>
            ))}
          </div>
        ) : null}
        {modelsErr && modelsFrom === null && (
          <p className="warn-block" style={{ marginTop: 6 }}>
            探测失败：{modelsErr}。可直接手填模型名。
          </p>
        )}

        <div className="model-row">
          <input
            className="text-input"
            value={nameDraft}
            onChange={(e) => setNameDraft(e.target.value)}
            placeholder={`配置名（如「我的 DeepSeek」）${savedName ? '' : '，留空自动命名'}`}
          />
          <button className="btn-mini" onClick={persist}>
            保存
          </button>
        </div>

        <div className="actions" style={{ marginTop: 8 }}>
          {/* 描边而不是实心：一屏只能有一个主按钮 —— 「生成参谋建议」才是主行动 */}
          <button
            className="btn-ghost"
            onClick={() => void applyUpstream()}
            disabled={applying || running}
          >
            {applying ? '应用中…' : '应用'}
          </button>
        </div>
        {upstreamMsg && <span className="hint">{upstreamMsg}</span>}
        <span className="hint">
          {saved.length ? '配置下次打开自动应用。' : '保存后下次打开自动应用。'}
          {' '}密钥<b>默认不存</b>本机，勾「记住密钥」才明文存浏览器（不上传第三方）；
          「清除全部」可一键清除。探测不计费。
        </span>

        {/* 参考知识库：通用辩题的素材面（非法条专用），检索后自动注入参谋上下文 */}
        <div className="kb-block">
          <span className="block-label">参考知识库（通用辩题素材）</span>
          <div className="model-row">
            <label className="btn-mini" style={{ cursor: 'pointer' }}>
              上传 .txt / .md
              <input
                type="file"
                accept=".txt,.md,text/plain"
                style={{ display: 'none' }}
                onChange={(e) => void uploadKb(e)}
              />
            </label>
            <span className="muted">
              {kb ? `${kb.files} 个文件 / ${kb.chunks} 块` : '读取中…'}
            </span>
          </div>
          <span className="hint">
            检索后自动注入参谋上下文（引用素材前请自行核对）。非法条素材请走这里。
          </span>
          {kbMsg && <span className="hint">{kbMsg}</span>}
        </div>
      </div>
      )}

      {tab === 'live' && (<>
      <div className="actions">
        <button
          className="btn-primary"
          disabled={running || noAdvisors || !topic.trim() || !opponentText.trim()}
          onClick={onSubmit}
        >
          {running ? '并行分析中…' : '生成参谋建议'}
        </button>
        <button className="btn-ghost" onClick={onReset} disabled={running}>
          清空结果
        </button>
      </div>

      {/* 花钱的动作就在这个按钮上，所以代价写在它下面而不是藏在文档里：
          「探测」模型名不计费，但每点一次分析就是五路各一次真实调用。 */}
      <span className="hint">
        点一次 = {advisorCount} 路并行 = {advisorCount} 次上游调用，超时的那几路照样计费；
        「探测」模型名与引用核验都不计费。
      </span>

      {noAdvisors && (
        <p className="warn-block">
          没有可用参谋（全部停用）——请在 configs/advisors.yaml 启用至少一路。
        </p>
      )}
      </>)}

      {tab === 'status' && (
      <div className="status">
        <div className="status-head">
          <span className="block-label">⑥ 服务状态</span>
          <button className="btn-mini" onClick={() => void check()} disabled={checking}>
            {checking ? '检测中…' : '重新检测'}
          </button>
        </div>
        {health ? (
          <ul className="status-list">
            <li><b>模型</b> {health.model}</li>
            {health.version && <li><b>版本</b> {health.version}</li>}
            {upstream && (
              <li>
                <b>上游</b> {KIND_LABELS[upstream.kind] ?? upstream.kind} · {upstream.host}
                {upstream.kind !== 'ollama' && (
                  <>
                    {' · 密钥 '}
                    <span className={upstream.key_set ? 'ok-text' : 'err-text'}>
                      {upstream.key_set ? '已设置' : '未设置'}
                    </span>
                  </>
                )}
              </li>
            )}
            <li><b>接入地址</b> {health.bridge}</li>
            <li>
              <b>参谋团</b>{' '}
              {health.advisors.length === 0
                ? '（未启用任何一路）'
                : health.advisors.map((a, i) => (
                    <span key={a.name}>
                      {i > 0 && ' · '}
                      {a.label}
                      {a.domain && <span className="roster-tag">{a.domain}</span>}
                    </span>
                  ))}
            </li>
            <li>
              <b>会话</b> {sessionId ? <code>{sessionId}</code> : '提交后创建'}
            </li>
          </ul>
        ) : (
          <p className="error">
            后端未连通{healthErr ? `：${healthErr}` : ''}
            <br />
            <span className="muted">
              启动 <code>python -m app.main</code> 与协议桥后重试。
            </span>
          </p>
        )}

        {/* ⑦ 本机台账会话 —— 以前只能增不能删：打过的记录会一直躺在本地 SQLite 里。
            这里列出来，让用户自己决定删哪一条（后端 DELETE 是级联的，见 store.delete_session）。 */}
        {health && (
          <div className="session-block">
            <span className="block-label">⑦ 本机台账会话</span>
            <div className="model-row">
              <span className="muted">
                {sessions.length
                  ? `最近 ${sessions.length} 条（本地 SQLite，不花上游调用）`
                  : '还没有会话 —— 生成一轮参谋后这里会出现'}
              </span>
              <button
                className="btn-mini"
                onClick={onRefreshSessions}
                disabled={running || deletingSessionId !== null}
              >
                刷新
              </button>
            </div>
            {sessionListErr && (
              <p className="warn-block" style={{ marginTop: 6 }}>{sessionListErr}</p>
            )}
            {sessions.length > 0 && (
              <ul className="session-items">
                {sessions.map((s) => (
                  <li key={s.id}>
                    <span className="session-topic" title={s.topic}>
                      {s.topic || '(无辩题)'}
                    </span>
                    <span className="muted">
                      {s.our_side} · {s.created_at}
                    </span>
                    <button
                      className="btn-mini danger"
                      disabled={deletingSessionId !== null || running}
                      onClick={() => onDeleteSession(s.id)}
                      title="连同对方发言、参谋卡、建议与核验记录一起删掉，不可恢复"
                    >
                      {deletingSessionId === s.id ? '删除中…' : '删除'}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <span className="hint">
              会话存在本机 SQLite。删一条会连同它的全部记录一起清掉。
            </span>
          </div>
        )}
      </div>
      )}
    </aside>
  )
}

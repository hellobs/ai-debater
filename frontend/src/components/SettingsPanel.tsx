import { useEffect, useState } from 'react'
import {
  BUDGET_PRESETS,
  type HealthInfo,
  type Topic,
  type UpstreamInfo,
  type UpstreamPatch,
} from '../types'

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
}) {
  const {
    topic, ourSide, opponentText, running, advisorCount, sessionId, budget,
    health, healthErr, onRecheck,
    topics, selectedTopicId, onSelectTopic, onSaveTopic, onDeleteTopic, saving,
    topicMsg,
    onTopic, onSide, onOpponent, onBudget, onSubmit, onReset,
    upstream, kinds, models, modelsErr, modelsFrom, onApplyUpstream, onRefreshModels,
  } = props

  const [checking, setChecking] = useState(false)

  // ---- 上游表单 ----
  // 初值来自后端；后端那边的值真变了（切换成功）才回填，避免每帧覆盖用户正在输入的内容。
  const [kind, setKind] = useState(upstream?.kind ?? 'ollama')
  const [baseUrl, setBaseUrl] = useState(upstream?.base_url ?? '')
  const [model, setModel] = useState(upstream?.model ?? '')
  /** 密钥**永不回填**（后端也不回传明文）。留空 = 沿用已有的那把。 */
  const [apiKey, setApiKey] = useState('')
  const [applying, setApplying] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  /** 清单是不是从"当前表单里这份配置"探来的。 */
  const staleModels = Boolean(
    modelsFrom && (modelsFrom.kind !== kind || modelsFrom.base_url !== baseUrl),
  )
  const [upstreamMsg, setUpstreamMsg] = useState<string | null>(null)

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
    }
    const err = await onApplyUpstream(patch)
    setApiKey('')
    setUpstreamMsg(err ?? `已切换：${KIND_LABELS[kind] ?? kind} · ${model || '(未指定模型)'}`)
    setApplying(false)
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
            : '辩题库来自 configs/topics.yaml（入仓预设）与 data/topics.json（本机自建）。选定辩题会自动带出立场。'}
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
          placeholder="把对方刚才的发言打进来（ASR 语音转写已规划在后置阶段）"
        />
      </label>

      <label className="block">
        <span className="block-label">④ 时间预算（现场调这个）</span>
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
            {budget}s 是按云端响应速度设的现场档。上游较慢时（例如本机 Ollama 的 8B，
            单路就要几十秒）多数参谋会被判「超时」—— 那种情况建议改选 120s 或「不限」。
          </p>
        )}
        <span className="hint">
          到点仍未返回的参谋会被标为「超时」并立刻交付，不阻塞已好的结果。
        </span>
      </label>

      <div className="block">
        <span className="block-label">⑤ 模型与上游</span>
        <select
          className="text-input"
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
            这个地址是本机 Ollama。直接选「本机 Ollama」形态更省事（免密钥）；
            用 OpenAI 兼容端点连它也合法 —— 两者说的是同一个端点。
          </p>
        )}

        {/* anthropic 形态下这个地址是**上游网关**，mavis 并不直连它（走内置协议桥转译）。
            不说明的话，填错协议就会变成"连上了但一直 404"，很难定位。 */}
        {kind === 'anthropic' && (
          <span className="hint">
            网关只认 Anthropic 协议，mavis 会经内置协议桥（<code>/bridge/v1</code>）转译后访问它。
          </span>
        )}

        {/* 本机 Ollama 不需要密钥 —— 摆一个禁用输入框只是占位噪音。
            切回 ollama 时还要把后端内存里那把旧密钥清掉（见 applyUpstream）。 */}
        {kind !== 'ollama' && (
          <input
            className="text-input"
            style={{ marginTop: 6 }}
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={upstream?.key_set ? '已保存一把密钥，留空即沿用' : 'API key'}
          />
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
            已探到一份清单，但它属于另一份配置（{sourceLabel(modelsFrom)}）。
            改动形态或地址后需重新「探测」，这份不作数。
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
            探测不到模型列表：{modelsErr}。可直接在上面手填模型名。
          </p>
        )}

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
          凭据只留在后端进程内存：不写文件、不回传前端、重启即失效。
          探测模型只列清单，不产生推理调用、不计费。
        </span>
      </div>

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

      {noAdvisors && (
        <p className="warn-block">
          没有可用的参谋（名册里五路都是 <code>enabled: false</code>），提交不会发出任何请求。
          请在 configs/advisors.yaml 至少启用一路。
        </p>
      )}

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
              先在 backend 目录启动 <code>python -m app.main</code>，
              并确保协议桥在跑。
            </span>
          </p>
        )}
      </div>
    </aside>
  )
}

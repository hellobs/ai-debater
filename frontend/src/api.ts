import type {
  AdvisorResult,
  AnalyzeInput,
  AsrResult,
  CorpusImportResult,
  CitationReport,
  Conflict,
  DonePayload,
  HealthInfo,
  LedgerCard,
  ModelsPayload,
  RetrievalStatus,
  SessionInfo,
  SessionRow,
  SessionSnapshot,
  Topic,
  TopicDraft,
  UpstreamInfo,
  UpstreamPatch,
} from './types'

export async function fetchHealth(): Promise<HealthInfo> {
  const res = await fetch('/api/health')
  if (!res.ok) throw new Error(`health ${res.status}`)
  return res.json()
}

// ---------------- 辩题库（纯本地，不消耗 API） ----------------

export async function fetchTopics(): Promise<Topic[]> {
  const res = await fetch('/api/topics')
  if (!res.ok) throw new Error(`topics ${res.status}`)
  return (await res.json()).topics ?? []
}

/** 存一条本机辩题。返回更新后的整个辩题库（含预设），前端直接整体替换。 */
export async function saveTopic(draft: TopicDraft): Promise<Topic[]> {
  const data = await jpost('/api/topics', draft)
  if (data.error) throw new Error(data.error)
  return data.topics ?? []
}

/** 删一条本机辩题。预设返回 ok=false（不入仓的那份才动得了）。 */
export async function deleteTopic(id: string): Promise<{ ok: boolean; topics: Topic[] }> {
  const res = await fetch(`/api/topics/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    headers: UI_GUARD,
  })
  const data = await res.json()
  return { ok: Boolean(data.ok), topics: data.topics ?? [] }
}

/**
 * 用 SSE 订阅参谋结果（**POST 形态**，输入走 JSON body）。
 * 事件顺序：session（会话与台账）→ advisor ×N → done
 * `budgetS` 原样透传；0 = 不限（关闭到点交付，仅受单次调用上限封顶）。
 *
 * 为什么不用 EventSource：它只支持 GET，对方发言被迫进 query —— 受服务端
 * 请求行上限约束（实测 ~32KB，语音转写的长发言可能撞上），且全文进访问日志
 * （体检 2026-09-30 的 P2-1）。改为 fetch 流式读取并自行解析 SSE 块，
 * 事件语义与旧版逐一对齐（含「出错不自动重跑」——重连会再花一次 token）。
 */
export function streamAnalyze(
  input: AnalyzeInput,
  sessionId: string | null,
  budgetS: number,
  handlers: {
    onSession?: (s: SessionInfo) => void
    onResult: (r: AdvisorResult) => void
    onDone: (d: DonePayload) => void
    onError: (msg: string) => void
  },
): () => void {
  const controller = new AbortController()
  let finished = false

  void (async () => {
    try {
      const res = await fetch('/api/analyze/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...UI_GUARD },
        body: JSON.stringify({
          topic: input.topic,
          our_side: input.our_side,
          opponent_text: input.opponent_text,
          // 辩题领域 → 后端的提示词包。空值不传，让后端走默认包。
          domain: input.domain || undefined,
          session_id: sessionId ?? undefined,
          // **预算必须显式发送，包括 0**：省略会让后端落到自己的默认档（30s），
          // 界面上「不限」就变成 30s —— 体检（2026-09-30）抓到的语义断裂。
          budget_s: budgetS,
        }),
        signal: controller.signal,
      })
      if (!res.ok || !res.body) {
        handlers.onError(`stream ${res.status}`)
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        // SSE 块以空行分隔；块内 event:/data: 行。: 开头是注释，忽略。
        let sep: number
        while ((sep = buffer.indexOf('\n\n')) >= 0) {
          const block = buffer.slice(0, sep)
          buffer = buffer.slice(sep + 2)
          let event = 'message'
          const dataLines: string[] = []
          for (const line of block.split('\n')) {
            if (line.startsWith('event:')) event = line.slice(6).trim()
            else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
          }
          if (!dataLines.length) continue
          const data = dataLines.join('\n')
          if (event === 'session') {
            try { handlers.onSession?.(JSON.parse(data)) } catch { /* 忽略 */ }
          } else if (event === 'advisor') {
            try {
              handlers.onResult(JSON.parse(data))
            } catch {
              handlers.onError('结果解析失败')
            }
          } else if (event === 'error') {
            // 后端 worker 崩溃时发 _error 后还会补发 done；这里与旧版一致：
            // 立即上报并断开。**不自动重跑**——重连会再花一次 token，
            // 已算好的路数由调用方从服务端快照补齐。
            let msg = '连接中断'
            try { msg = JSON.parse(data).error ?? msg } catch { /* 保留默认 */ }
            handlers.onError(msg)
            controller.abort()
            return
          } else if (event === 'done') {
            finished = true
            try {
              handlers.onDone(JSON.parse(data) as DonePayload)
            } catch {
              handlers.onDone({ session_id: sessionId ?? '', latency_s: 0, our_ledger: [] })
            }
            controller.abort()
            return
          }
        }
      }
      if (!finished) handlers.onError('连接中断')
    } catch (e) {
      // abort 主动取消不算错误（清空结果 / done 后的收尾都会走到这）
      if (!finished && (e as Error)?.name !== 'AbortError') handlers.onError('连接中断')
    }
  })()

  return () => controller.abort()
}

// ---------------- 上游与模型（运行时可改；凭据只驻留后端内存） ----------------

export async function fetchUpstream(): Promise<{
  upstream: UpstreamInfo
  kinds: string[]
}> {
  const res = await fetch('/api/upstream')
  if (!res.ok) throw new Error(`upstream ${res.status}`)
  return res.json()
}

/** 只提交要改的字段。返回切换后的（脱敏）上游快照。 */
export async function setUpstream(patch: UpstreamPatch): Promise<UpstreamInfo> {
  const data = await jpost('/api/upstream', patch)
  if (!data.ok) throw new Error(data.detail ?? data.error ?? '切换失败')
  return data.upstream as UpstreamInfo
}

/**
 * 探测可用模型。**不产生推理调用，不计费。**
 * 不传参数 = 探测当前生效的上游。
 */
export async function fetchModels(kind?: string, baseUrl?: string): Promise<ModelsPayload> {
  const params = new URLSearchParams()
  if (kind) params.set('kind', kind)
  if (baseUrl) params.set('base_url', baseUrl)
  const res = await fetch(`/api/models?${params.toString()}`)
  if (!res.ok) throw new Error(`models ${res.status}`)
  return res.json()
}

// ---------------- 台账 CRUD ----------------

/**
 * 跨站请求伪造（CSRF）防护头：浏览器**无法**在跨站简单请求里携带自定义头
 * （自定义头会强制 CORS 预检并被拦），而后端对计费/写盘端点强制要求它。
 * 所以「带上它」= 证明请求来自本界面。命名见后端 main.py 的 csrf_guard。
 */
const UI_GUARD = { 'X-Debater-UI': '1' }

/**
 * 统一的响应校验：非 2xx 一律抛错，并带上后端的 `detail`。
 *
 * 为什么必须有：后端对「会话/资源不存在」已改回正确错误码（见 main.py）——
 * 不看 `res.ok` 就会把**失败的写入当成成功**：界面显示「已采纳 / 已记录」，
 * 而库里什么都没发生（`setLedger(data.cards ?? [])` 还会顺手把台账清空）。
 * 调用方本来就有 try/catch（handleAdopt / FeedbackRow / 各处 fetchSession），
 * 此前只是永远走不到 —— 这个 helper 把那条路接通。
 */
async function ensureOk(res: Response): Promise<Response> {
  if (res.ok) return res
  let detail = `HTTP ${res.status}`
  try {
    const body = await res.json()
    if (body?.detail) detail = String(body.detail)
  } catch {
    /* 非 JSON 错误体：保留状态码即可 */
  }
  throw new Error(detail)
}

async function jpost(url: string, body?: unknown) {
  const res = await ensureOk(
    await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json', ...UI_GUARD },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  )
  return res.json()
}

export async function addCard(
  sessionId: string,
  card: {
    claim: string
    major_premise?: string
    minor_premise?: string
    conclusion?: string
    source?: string
  },
): Promise<{ card: { id: string }; cards: LedgerCard[] }> {
  return jpost(`/api/session/${sessionId}/cards`, card)
}

export async function patchCard(cardId: string, status: string) {
  const res = await ensureOk(
    await fetch(`/api/cards/${cardId}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json', ...UI_GUARD },
      body: JSON.stringify({ status }),
    }),
  )
  return res.json()
}

export async function deleteCard(cardId: string) {
  const res = await ensureOk(
    await fetch(`/api/cards/${cardId}`, { method: 'DELETE', headers: UI_GUARD }),
  )
  return res.json()
}

export async function fetchSession(sessionId: string): Promise<SessionSnapshot> {
  const res = await ensureOk(await fetch(`/api/session/${sessionId}`))
  return res.json()
}

/** 本机台账里的会话列表（最近的若干条，按时间倒序）。纯本地 SQLite，不花上游调用。 */
export async function listSessions(limit = 20): Promise<SessionRow[]> {
  const res = await fetch(`/api/sessions?limit=${encodeURIComponent(limit)}`)
  if (!res.ok) throw new Error(`sessions ${res.status}`)
  return ((await res.json()).sessions ?? []) as SessionRow[]
}

export async function deleteSession(sessionId: string): Promise<{ ok: boolean }> {
  const res = await ensureOk(
    await fetch(`/api/session/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
      headers: UI_GUARD,
    }),
  )
  return res.json()
}

/** 立场一致性检测：把新生成的建议与台账比对（第二道闸） */
export async function checkConsistency(
  sessionId: string,
  claims: string[],
): Promise<Conflict[]> {
  const data = await jpost(`/api/session/${sessionId}/check-consistency`, { claims })
  return data.conflicts ?? []
}

// ---------------- 引用核验（纯本地，不消耗 API） ----------------

export async function verifyCitations(sessionId: string): Promise<CitationReport> {
  return jpost(`/api/session/${sessionId}/verify-citations`, {})
}

export async function fetchRetrievalStatus(reload = false): Promise<RetrievalStatus> {
  const res = await fetch(`/api/retrieval${reload ? '?reload=true' : ''}`)
  return res.json()
}

/** 导入一段法条全文进语料库（纯本地，0 消耗）。同名法整体替换，导入即热重载生效。 */
export async function importCorpus(law: string, text: string): Promise<CorpusImportResult> {
  return jpost('/api/corpus/import', { law, text })
}

// ---------------- 语音转写（阶段 7 一期：纯本地，不消耗 API） ----------------

/**
 * 上传一段裸 PCM（16bit 小端、单声道）转成文字。
 * 结果只负责填进「对方刚说的话」输入框，**不自动触发分析**——
 * 识别错字由人核对后再提交，决策权在用户。
 */
export async function transcribePcm(
  pcm: ArrayBuffer,
  sampleRate: number,
): Promise<AsrResult> {
  const res = await fetch('/api/asr/transcribe', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/octet-stream',
      'X-Sample-Rate': String(sampleRate),
      ...UI_GUARD,
    },
    body: pcm,
  })
  if (!res.ok) {
    let detail = `asr ${res.status}`
    try { detail = (await res.json()).detail ?? detail } catch { /* 保留默认 */ }
    throw new Error(detail)
  }
  return res.json()
}

// ---------------- 反馈闭环（评分 / 收录为训练样本）与参考知识库 ----------------

/** 提交对某一路参谋的反馈。rating 1–5 可选；selected=收录为训练样本。 */
export async function saveFeedback(
  sessionId: string,
  advisor: string,
  rating: number | null,
  selected: boolean,
): Promise<void> {
  await jpost(`/api/feedback?session_id=${encodeURIComponent(sessionId)}`,
    { advisor, rating, selected })
}

/** 上传一份无结构参考素材（.txt/.md），上传即生效并注入参谋上下文。 */
export async function uploadKnowledge(name: string, text: string): Promise<{ ok: boolean; error?: string; chunks?: number }> {
  return jpost('/api/knowledge/upload', { name, text })
}

export async function knowledgeStatus(): Promise<{ files: number; chunks: number }> {
  const res = await fetch('/api/knowledge/status')
  return res.json()
}

/** 取回该会话已持久化的最近一次引用核验报告（刷新后恢复用）。 */
export async function fetchLatestCitations(
  sessionId: string,
): Promise<CitationReport | null> {
  const res = await fetch(`/api/session/${encodeURIComponent(sessionId)}/citations/latest`)
  const data = await res.json()
  return data.report ?? null
}

import type {
  AdvisorResult,
  AnalyzeInput,
  CitationReport,
  Conflict,
  DonePayload,
  HealthInfo,
  LedgerCard,
  MetricsInfo,
  RetrievalStatus,
  SessionInfo,
  SessionSnapshot,
} from './types'

export async function fetchHealth(): Promise<HealthInfo> {
  const res = await fetch('/api/health')
  if (!res.ok) throw new Error(`health ${res.status}`)
  return res.json()
}

export async function fetchMetrics(): Promise<MetricsInfo> {
  const res = await fetch('/api/metrics')
  if (!res.ok) throw new Error(`metrics ${res.status}`)
  return res.json()
}

/**
 * 用 SSE 订阅参谋结果。
 * 事件顺序：session（会话与台账）→ advisor ×N → done
 * `budgetS` 为 0 或不传表示不限时间预算。
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
  const params = new URLSearchParams({
    topic: input.topic,
    our_side: input.our_side,
    opponent_text: input.opponent_text,
  })
  if (sessionId) params.set('session_id', sessionId)
  if (budgetS > 0) params.set('budget_s', String(budgetS))

  const es = new EventSource(`/api/analyze/stream?${params.toString()}`)
  let finished = false

  es.addEventListener('session', (ev) => {
    try {
      handlers.onSession?.(JSON.parse((ev as MessageEvent).data))
    } catch {
      /* 忽略 */
    }
  })

  es.addEventListener('advisor', (ev) => {
    try {
      handlers.onResult(JSON.parse((ev as MessageEvent).data))
    } catch {
      handlers.onError('结果解析失败')
    }
  })

  es.addEventListener('done', (ev) => {
    finished = true
    try {
      handlers.onDone(JSON.parse((ev as MessageEvent).data) as DonePayload)
    } catch {
      handlers.onDone({ session_id: sessionId ?? '', latency_s: 0, our_ledger: [] })
    }
    es.close()
  })

  es.addEventListener('error', () => {
    if (finished) return
    // 不在这里自动重跑：重连会再花一次 token。改为提示 + 由前端从服务端快照补齐。
    handlers.onError('连接中断')
    es.close()
  })

  return () => es.close()
}

// ---------------- 台账 CRUD ----------------

async function jpost(url: string, body?: unknown) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
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
  const res = await fetch(`/api/cards/${cardId}`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ status }),
  })
  return res.json()
}

export async function deleteCard(cardId: string) {
  const res = await fetch(`/api/cards/${cardId}`, { method: 'DELETE' })
  return res.json()
}

export async function fetchSession(sessionId: string): Promise<SessionSnapshot> {
  const res = await fetch(`/api/session/${sessionId}`)
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

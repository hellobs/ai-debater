export interface Rebuttal {
  claim: string
  major_premise: string
  minor_premise: string
  conclusion: string
}

export interface AuditFinding {
  fallacy: string
  quote: string
  explain: string
}

/** 解释方法争夺点 */
export interface MethodNote {
  opponent_method: string
  opponent_effect: string
  our_method: string
  counter: string
}

/** 风险提示 */
export interface RiskItem {
  risk: string
  kind: string
  suggestion: string
}

export type AdvisorStatus = 'ok' | 'error' | 'empty' | 'timeout'

export interface AdvisorResult {
  advisor: string
  label: string
  status: AdvisorStatus
  latency_s: number
  payload: unknown
  raw: string | null
  error: string | null
  kind: 'rebuttal' | 'questions' | 'audit' | 'text' | 'meta' | string
}

/** 一路参谋的元数据。来源是 /api/health —— 前端不再自己维护一份名册。 */
export interface AdvisorMeta {
  name: string
  label: string
  kind: string
  /** 场景领域。空 = 通用；非空 = 该场景专用（如「法学」）。 */
  domain: string
}

/**
 * mavis provider 的快照（来源 /api/health）。
 *
 * `summary.summary` 是 mavis 原样的计数器格式：键是调用名（本项目用参谋名），
 * 值是 `S:成功,F:最终失败/R:完成的请求数` 字符串。`total` 是 mavis 自己维护的总计。
 *
 * ⚠️ `R` **不是**重试次数：它只在成功拿到响应时递增，抛异常的尝试完全不计入
 * （重试 3 次全失败时 `R` 是 0）。要算成功率用 `S/(S+F)`，别用 `R` 当分母。
 */
export interface ProviderSummary {
  model: string
  summary: Record<string, string>
}

export interface ProviderCacheStats {
  hits: number
  misses: number
  hit_rate: number
  cache_size: number
}

export interface ProviderInfo {
  ready: boolean
  is_available?: boolean
  summary?: ProviderSummary
  /** null = 该 provider 没实现 cache_stats（它不在 LLMProvider 基类契约里） */
  cache?: ProviderCacheStats | null
  error?: string
}

export interface ObserverRunInfo {
  advisors: string[]
  budget_s: number | null
  counts: Record<string, number>
  total_latency_s: number | null
}

/** 本进程的实时观察数据（跨会话的历史分布看 /api/metrics）。 */
export interface ObserverInfo {
  runs: number
  by_advisor: Record<string, Record<string, number>>
  last_run: ObserverRunInfo | null
}

export interface HealthInfo {
  ok: boolean
  /** 站点品牌名（后端 config.BRAND_NAME，与 FastAPI title 同源） */
  brand?: string
  model: string
  bridge: string
  upstream_configured: boolean
  budget_s?: number
  advisors: AdvisorMeta[]
  /** mavis 接入状态（provider 计数 / 可用性 / 缓存） */
  provider?: ProviderInfo
  /** 本进程观察者（落库 / 推流 / 指标）的实时计数 */
  observers?: ObserverInfo
}

/** 一条辩题。双方立场是辩题的一部分，不是并列的独立配置。 */
export interface Topic {
  id: string
  title: string
  domain: string
  side_a: string
  side_b: string
  /** 对方最可能的第一句话，用于「对方刚说的话」一键填充 */
  opponent_hint: string
  note: string
  /** preset = 入仓预设（删不掉）；local = 本机自建（可删） */
  source: 'preset' | 'local' | string
}

export interface TopicDraft {
  title: string
  id?: string
  domain?: string
  side_a?: string
  side_b?: string
  opponent_hint?: string
  note?: string
}

export interface AnalyzeInput {
  topic: string
  our_side: string
  opponent_text: string
}

// ---------------- 论点台账（阶段 3） ----------------

export type CardStatus = 'standing' | 'weakened' | 'abandoned'

export interface LedgerCard {
  id: string
  session_id: string
  claim: string
  major_premise: string
  minor_premise: string
  conclusion: string
  source: string
  status: CardStatus
  challenged_count: number
  created_at: string
}

export interface Conflict {
  card_id: string
  card_claim: string
  new_claim: string
  reason: string
}

export interface SessionInfo {
  session_id: string
  our_ledger: string[]
  advisors: string[]
}

export const STATUS_LABEL: Record<CardStatus, string> = {
  standing: '成立',
  weakened: '受损',
  abandoned: '放弃',
}

// ---------------- 现场保障（阶段 5） ----------------

export interface AdvisorMetrics {
  total: number
  ok: number
  timeout: number
  error: number
  empty: number
  p50: number | null
  p95: number | null
  max: number | null
  ok_rate: number | null
}

export interface MetricsInfo {
  budget_s: number
  bridge: string
  advisors: Record<string, AdvisorMetrics>
}

export interface DonePayload {
  session_id: string
  latency_s: number
  our_ledger: string[]
  budget_s?: number
}

/** 现场模式预设的时间预算（秒） */
export const BUDGET_PRESETS = [
  { label: '现场模式 8s', value: 8 },
  { label: '现场模式 12s', value: 12 },
  { label: '宽松 20s', value: 20 },
  { label: '不限（等到全部返回）', value: 0 },
]

export interface StoredSuggestion {
  id: number
  session_id: string
  advisor: string
  status: string | null
  latency_s: number | null
  payload: unknown
  created_at: string
}

export interface SessionSnapshot {
  session: { id: string; topic: string; our_side: string; created_at: string }
  turns: { id: number; opponent_text: string; created_at: string }[]
  cards: LedgerCard[]
  suggestions: StoredSuggestion[]
}

// ---------------- 引用核验（阶段 4，纯本地零消耗） ----------------

export type CitationStatus = 'verified' | 'dubious' | 'unverified'

export interface CitationCheck {
  raw: string
  law: string
  article: string
  status: CitationStatus
  evidence: string
  origin: string
  note: string
}

export interface CitationReport {
  total: number
  verified: number
  dubious: number
  unverified: number
  retriever: string
  items: CitationCheck[]
}

export interface RetrievalStatus {
  name: string
  available: boolean
  corpus_dir?: string
  laws?: number
  articles?: number
  documents?: number
}

export const CITATION_LABEL: Record<CitationStatus, string> = {
  verified: '已核验',
  dubious: '存疑',
  unverified: '未核验',
}


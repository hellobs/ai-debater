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

export interface HealthInfo {
  ok: boolean
  model: string
  bridge: string
  upstream_configured: boolean
  advisors: { name: string; label: string }[]
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


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

export type AdvisorStatus = 'ok' | 'error' | 'empty'

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


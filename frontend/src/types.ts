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

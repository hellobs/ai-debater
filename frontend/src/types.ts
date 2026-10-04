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

/** 衡量尺度争夺点（字段名沿用后端 `*_method`，措辞由辩题领域的提示词包决定） */
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

/** mavis 被本项目用上的一个面（来源 /api/health.mavis.surfaces）。 */
export interface MavisSurface {
  key: string
  /** 中文名，如「模型接入」 */
  name: string
  /** mavis 侧的入口，如 `prompt.Scratch.build_prompt()` */
  entry: string
  /** 本项目里的落点，如 `mavis_bridge.render()` */
  used_in: string
  detail: string
}

/**
 * 本项目的基座框架：mavis（发行包 `mavisframework`）。
 *
 * `based_on` 不是装饰 —— 本项目**基于 `mavisframework` 开发**，而非"碰巧调用过它"。
 * `readonly: true` 不是形容词 —— mavis 以只读依赖接入、仓库一行未改，
 * 所以 `docs/mavis-gap-report.md` 里的结论对**框架本身**成立。
 * `contact` 是唯一允许 import `mavisframework` 的文件（有 AST 测试守着）。
 */
export interface MavisInfo {
  framework: string
  /** 基座框架的发行包名，后端写死为 `mavisframework` */
  based_on?: string
  version: string
  readonly: boolean
  contact: string
  surfaces: MavisSurface[]
  /** 用不上的半边（架构性错位，有证据） */
  unused: string
  prompts: { dir: string; templates: number; names?: string[] }
  /** 有哪些领域提示词包、哪个兜底。唯一来源是 configs/prompt-packs.yaml */
  packs?: PromptPackInfo
  /** 挂在 mavis 插件总线上的观察者名字 */
  observers?: string[]
}

/** 领域提示词包的配置自述。本轮用了哪个包由 session 事件回传（`prompt_pack`）。 */
export interface PromptPackInfo {
  /** 兜底包名：没有包认领该领域时用它 */
  default: string
  count: number
  packs: { name: string; label: string; hint: string; domains: string[] }[]
  /** 包所在目录（prompts/packs） */
  dir: string
}

/** 语音转写的就绪状态，来自 /api/health 的 asr 块。 */
export interface AsrStatus {
  /** 批式引擎名：sherpa-sensevoice / none。前端不据此分支，只展示 */
  engine: string
  /** 批式转写是否就绪（SenseVoice 模型已下载） */
  available: boolean
  /** 流式转写（二期，边说边出字）是否就绪——界面收音按钮以此为准 */
  stream?: boolean
  /** 已找到的模型标识；未就绪时为 null */
  model?: string | null
  /** 不可用原因（如「模型未下载，先运行 fetch_asr_model.sh」）；给界面直说 */
  reason?: string | null
}

/** /api/asr/transcribe 的响应。ok=false 时 error 必有值。 */
export interface AsrResult {
  ok: boolean
  text?: string
  duration_s?: number
  engine?: string
  latency_s?: number
  error?: string
}

/** 语料导入结果（POST /api/corpus/import）。ok=false 时 error 说明怎么修。 */
export interface CorpusImportResult {
  ok: boolean
  /** 本次导入的法名（从标题识别或用户填写） */
  law?: string
  /** 本次导入解析出的条款数 */
  articles?: number
  /** 解析器的非致命提示（如法名取自标题） */
  warnings?: string[]
  /** 语料库全貌（导入后） */
  total_laws?: number
  total_articles?: number
  error?: string
}

export interface HealthInfo {
  ok: boolean
  /** 站点品牌名（后端 config.BRAND_NAME，与 FastAPI title 同源） */
  brand?: string
  /** 服务版本（唯一来源是后端 main.py 的 VERSION；界面只读，不自己抄一份） */
  version?: string
  model: string
  bridge: string
  upstream_configured: boolean
  budget_s?: number
  advisors: AdvisorMeta[]
  /** 底座 mavis 的接入自述（版本 / 三面 / 唯一接触面 / 模板清单） */
  mavis?: MavisInfo
  /** mavis 接入状态（provider 计数 / 可用性 / 缓存） */
  provider?: ProviderInfo
  /** 本进程观察者（落库 / 推流 / 指标）的实时计数 */
  observers?: ObserverInfo
  /** 语音转写就绪状态；后端版本过旧没有这个块时按「不可用」处理 */
  asr?: AsrStatus
}

/**
 * 当前生效的上游（模型接入）。**凭据只报有没有（`key_set`），不报是什么。**
 *
 * `base_url` 的含义随 `kind` 变：ollama/openai 下就是模型端点地址；
 * anthropic 下是**上游网关**地址（mavis 实际打的是内嵌桥，见 `mavis_base_url`）。
 */
export interface UpstreamInfo {
  kind: string
  base_url: string
  model: string
  key_set: boolean
  /** mavis 实际访问的地址（anthropic 形态下指向后端自己的 /bridge/v1） */
  mavis_base_url: string
  host: string
}

/** 切换上游时只提交要改的字段；`api_key` 省略 = 不动（不是清空）。 */
export interface UpstreamPatch {
  kind?: string
  base_url?: string
  model?: string
  api_key?: string
}

export interface ModelsPayload {
  ok: boolean
  models: string[]
  /** 探测失败的说明。探测不到就照实说，前端退回手填。 */
  error: string
  /** 这份清单**属于哪份配置** —— 改了形态/地址还没重探时，它就是过期的。 */
  kind: string
  base_url: string
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
  /**
   * 辩题领域（选中辩题自带的 `domain`）。后端据此选领域提示词包：
   * 「AI + 法学」→ legal 包，其余 → general 包。
   *
   * 前端只把 domain 原样送过去，**不做 domain→包的映射** ——
   * 那份映射在后端（configs/prompt-packs.yaml），这里再写一遍就是两份真相。
   * 实际生效的包名由后端的 session 事件回传（`prompt_pack` / `pack_label`）。
   */
  domain?: string
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

/**
 * 一条要「采纳进台账」的卡片内容。
 *
 * 由哪条参谋产出、怎么映射成卡片，**唯一来源是 `adopt.ts::cardFor()`** ——
 * 界面上的采纳按钮与一致性检测的"新主张"抽取都从那里取，避免两处各写一份。
 */
export interface AdoptCard {
  claim: string
  major_premise: string
  minor_premise: string
  conclusion: string
  source: string
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
  /** 本轮实际生效的领域提示词包名（由后端解析，前端不复刻映射） */
  prompt_pack?: string
  /** 该包的显示名，如「法学」「通用」 */
  pack_label?: string
}

/** `/api/sessions` 里的一条台账会话（前端只拿这几个字段显示 + 删除用）。
 *  形状由后端 SQLite 的 sessions 表决定（id / topic / our_side / created_at），
 *  这里不复刻，免得改表时前端先有一份错的。 */
export interface SessionRow {
  id: string
  topic: string
  our_side: string
  created_at: string
}

export const STATUS_LABEL: Record<CardStatus, string> = {
  standing: '成立',
  weakened: '受损',
  abandoned: '放弃',
}

// ---------------- 现场保障（阶段 5） ----------------
//
// 延迟仪表（P50 / P95 面板）已从界面移除：现场真正需要的是"到点交付"，
// 不是盯着分位数看。后端 /api/metrics 仍在（导出与测试用），所以这里不再留类型。

export interface DonePayload {
  session_id: string
  latency_s: number
  our_ledger: string[]
  budget_s?: number
}

/** 现场模式预设的时间预算（秒） */
/**
 * 时间预算档位。**默认档不写在这里** —— 它由 `/api/health` 的 `budget_s`
 * （即后端的 `ADVISOR_BUDGET_S`）决定，见 App.tsx。
 *
 * 为什么默认不能是前端常量：界面每次请求都会显式带 `budget_s`，一旦前端写死
 * 12s，后端把 `ADVISOR_BUDGET_S` 调到 120（本地模型模式就是这么做的）也会被
 * 界面盖掉，表现为"环境改了没用、超时照样一大片"—— 这种故障看不出因果。
 */
export const BUDGET_PRESETS = [
  { label: '现场模式 12s', value: 12 },
  { label: '现场模式 20s', value: 20 },
  { label: '宽松 30s', value: 30 },
  // 30s 与 120s 之间原本是空档：本地 8B 五路实测约 50s，卡在这中间没有可选值，
  // 只能在"超时一大片"和"等两分钟"之间二选一。
  { label: '宽松 60s（本地 8B 够用）', value: 60 },
  { label: '本地模型 120s', value: 120 },
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
  /** 引用处模型**声称的规范内容**（后端抽出来的）。空串 = 模型没写内容 */
  claimed: string
  /** 与语料原文的最长公共子串重合度 0~1；null = 无法比对（缺任一侧） */
  match: number | null
  /**
   * 重合度是否达标。null = 未比对；false = **引述与语料原文对不上**，值得人工看一眼。
   *
   * 注意它**不改变** `status`：条款存在与否（存在性）与引述内容对不对（一致性）
   * 是两个正交的维度 —— 真实条款号 + 编造内容是完全可能的。
   */
  content_ok: boolean | null
}

export interface CitationReport {
  total: number
  verified: number
  dubious: number
  unverified: number
  /** `verified` 里"条款存在、但引述与原文对不上"的条数 */
  content_suspect: number
  /** 内容比对的重合度阈值，由后端下发（前端不自己抄一份数字） */
  match_low: number
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


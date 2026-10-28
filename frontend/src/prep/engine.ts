/** 备赛本地立论引擎 —— 从「辩论教练」面板移植（业务逻辑归我们，实现等价）。
 *
 * 三层供料：辩题库命中（实录级材料）→ 通用立论引擎（按题型变体句 + 贴题例证）
 * → 用户在表单里精修。AI（/api/prep/ai）只是更好的供料器，离线时引擎照样出活。
 *
 * 反幻觉口径与生成侧一致：例证引用带来源，检索不到就明确提示"自行补一条可查证事实"。
 */
import DATA from '../data/prep/debate-data.json'

export type Side = 'pro' | 'con'
export type TopicType = 'value' | 'fact' | 'policy'

export interface BankEntry {
  name: string
  k: string[]
  pro: { def: string; std: string; pts: string[]; val: string; q: string[] }
  con: { def: string; std: string; pts: string[]; val: string; q: string[] }
}
export interface ThemeEntry {
  name: string
  k: string[]
  kWeak?: string[]
  ex: string[]
}
export interface PersonEntry {
  n: string
  theme: string
  k: string[]
  f: string
  pro: string
  con: string
  tip?: string
}
export interface QuoteEntry { q: string; c: string; src?: string }
export interface ArenaQuestion { t: string; src: string; q: string; tip: string }

const BANK = DATA.BANK as BankEntry[]
const THEME_EX = DATA.THEME_EX as ThemeEntry[]
const PERSON_EX = DATA.PERSON_EX as PersonEntry[]
const QUOTES = DATA.QUOTES as QuoteEntry[]
export const ARENA_QUESTIONS = (DATA.QUESTIONS ?? []) as ArenaQuestion[]

// ---------------- 题型判定与拆题 ----------------
export function detectType(t: string): TopicType {
  if (/该不该|应不应该|应否|要不要|可不可以|应不应当/.test(t)) return 'policy'
  if (/更重要|更值得|更利|更应|利大于弊|弊大于利|哪个更/.test(t)) return 'value'
  return 'fact'
}

const TOPIC_MODALS: [string, [string, string]][] = [
  ['应不应该', ['应该', '不应该']], ['应不应当', ['应当', '不应当']],
  ['该不该', ['该', '不该']], ['要不要', ['要', '不要']],
  ['可不可以', ['可以', '不可以']], ['能不能', ['能', '不能']],
  ['会不会', ['会', '不会']], ['是不是', ['是', '不是']],
  ['应否', ['应当', '不应当']], ['是否', ['是', '不是']],
]
const MODAL_NEG: Record<string, string> = {
  应该: '不应该', 应当: '不应当', 要: '不要', 可以: '不可以',
  能: '不能', 会: '不会', 是: '不是', 该: '不该',
}

/** 把任意辩题拆成「正方主张 / 反方主张」（覆盖 6 种常见命题形态） */
export function parseTopic(t: string): { pro: string; con: string } {
  let raw = String(t ?? '').replace(/[？?。！!]+$/, '').trim()
  raw = raw.replace(/是否应该/g, '应不应该').replace(/是否应当/g, '应不应当').replace(/是否该/g, '该不该')
  if (!raw) return { pro: '', con: '' }

  // ① 斜杠式：AI 的发展应该/不应该以友善为前提
  const sl = raw.split(/[/／]/).map((s) => s.trim()).filter(Boolean)
  if (sl.length >= 2) {
    const a = sl[0], b = sl.slice(1).join('/')
    const tail = a.match(/(应该|应当|要|可以|能|会|是|该)$/)
    if (tail) {
      const pos = tail[1], neg = MODAL_NEG[pos]
      if (neg && b.indexOf(neg) === 0) {
        const prefix = a.slice(0, a.length - pos.length), rest = b.slice(neg.length)
        return { pro: prefix + pos + rest, con: prefix + neg + rest }
      }
    }
    return { pro: a, con: b }
  }

  // ② A还是B
  if (raw.indexOf('还是') >= 0) {
    const seg = raw.split('还是')
    const L = seg[0].trim(), R = seg.slice(1).join('还是').trim()
    if (/利大于弊|弊大于利/.test(L)) {
      const base = L.replace(/利大于弊|弊大于利/g, '')
      return { pro: base + '利大于弊', con: base + '弊大于利' }
    }
    const cmp = (L.match(/(更重要|更值得|更有利|更可靠|更明智|更好|更难|更易|更应)$/) || ['', ''])[1]
    if (cmp && R.indexOf(cmp) < 0) return { pro: L, con: R + cmp }
    let subj = '', modal = ''
    for (const [q, pair] of TOPIC_MODALS) {
      const at = L.indexOf(q)
      if (at > 0) { subj = L.slice(0, at); modal = pair[0]; break }
    }
    if (!subj) {
      const at = L.search(/应该|应当/)
      if (at > 0) { subj = L.slice(0, at); modal = L.slice(at, at + 2) }
    }
    if (subj && R.indexOf(subj) < 0) return { pro: L, con: subj + modal + R }
    return { pro: L, con: R }
  }

  // ③ 该不该X / 应不应该X / 要不要X
  for (const [q, pair] of TOPIC_MODALS) {
    const at = raw.indexOf(q)
    if (at >= 0) {
      const subj = raw.slice(0, at), rest = raw.slice(at + q.length)
      return { pro: subj + pair[0] + rest, con: subj + pair[1] + rest }
    }
  }

  // ④ X合理吗 / X对吗
  if (/[吗呢]$/.test(raw) && !/应该|应当|该不该|应不应该|要不要|可不可以|能不能|会不会|是不是|是否/.test(raw)) {
    const base = raw.replace(/[吗呢]+$/, '')
    const adj = /(合理|可取|值得|可怕|正确|可行)/.exec(base)
    if (adj) return { pro: base, con: base.replace(adj[1], '不' + adj[1]) }
    return { pro: base, con: '反对「' + base + '」' }
  }

  // ⑤ 裸模态「应该」
  const bare = raw.replace(/[吗呢]+$/, '')
  const bat = bare.search(/应该|应当/)
  if (bat > 0) {
    const neg = bare.slice(bat, bat + 2) === '应当' ? '不应当' : '不应该'
    return { pro: bare, con: bare.slice(0, bat) + neg + bare.slice(bat + 2) }
  }

  // ⑥ 兜底
  return { pro: raw, con: '反对「' + raw + '」' }
}

export function claimOf(t: string, side: Side): string {
  const p = parseTopic(t)
  return side === 'pro' ? p.pro : p.con
}

// ---------------- 匹配 ----------------
export function matchBank(t: string): BankEntry | null {
  const low = t.toLowerCase()
  return BANK.find((b) => b.k.some((k) => low.includes(k.toLowerCase()))) || null
}

export function matchTheme(t: string): ThemeEntry | null {
  const kw = t.toLowerCase()
  let best: ThemeEntry | null = null, bs = 0
  for (const th of THEME_EX) {
    const strong = (th.k || []).reduce((a, k) => a + (kw.includes(k.toLowerCase()) ? Math.min(k.length, 4) * 2 : 0), 0)
    const weak = (th.kWeak || []).reduce((a, k) => a + (kw.includes(k.toLowerCase()) ? 1 : 0), 0)
    const sc = strong + weak
    if (sc > bs) { bs = sc; best = th }
  }
  return best
}

const MAP_QUOTES: [string, string][] = [
  ['金钱', '金钱与欲望'], ['万恶', '金钱与欲望'], ['误解', '表达与误解'],
  ['表达', '表达与误解'], ['人性', '人性与善恶'], ['善恶', '人性与善恶'],
  ['知难', '知与行'], ['知易', '知与行'], ['理想', '理想与人生'],
  ['共情', '价值与共情'], ['理解', '价值与共情'], ['宿命', '表达与误解'],
]
export function matchQuotes(t: string): string[] {
  const t2 = t.toLowerCase()
  const hit = MAP_QUOTES.find((m) => t2.includes(m[0]))
  const pool = hit
    ? QUOTES.filter((q) => q.c === hit[1]).map((q) => q.q)
    : QUOTES.filter((q) => q.c === '认知与哲学').map((q) => q.q)
  return pool.slice(0, 2)
}

// ---------------- 关键词与例证排序 ----------------
export function exSegs(t: string): string[] {
  return t.split(/还是|该不该|应不应该|要不要|可不可以|是否|能不能|会不会|更重要|更值得|利大于弊|弊大于利|吗|？|\?|，|,|、|与|和|比|／|\/|\s/)
    .map((s) => s.trim()).filter((s) => s.length >= 2)
}
const STOP = new Set(['应该', '不该', '可以', '不可以', '是否', '能否', '我们', '他们', '这个', '那个', '什么', '怎么', '为什么', '一定', '真的', '其实', '而且', '但是', '因为', '所以', '如果', '就是', '还是', '这样', '那样', '一个', '没有', '不是', '不能'])
const MODAL_STRIP = /(应不应该|应不应当|该不该|要不要|可不可以|能不能|会不会|是不是|不应该|不应当|不要|不可以|不能|不会|不是|应该|应当|是否|应否|或者|还是)/g
const MODAL_EDGE = /^(该|要|会|能|是|可以|应)+|(该|要|会|能|是|可以|应|吗|呢)+$/g

export function topicKeys(t: string): string[] {
  const cleaned = String(t ?? '')
    .replace(MODAL_STRIP, ' ')
    .replace(/[？?。，,、！!；;：:「」『』“”"']/g, ' ')
  const picks = [...new Set(
    exSegs(cleaned).map((s) => s.replace(MODAL_EDGE, '').trim())
      .filter((s) => s.length >= 2 && !STOP.has(s))
  )].sort((a, b) => b.length - a.length).slice(0, 3)
  if (picks.length) return picks
  const raw = [...new Set(exSegs(t).filter((s) => s.length >= 2 && !STOP.has(s)))]
    .sort((a, b) => b.length - a.length).slice(0, 3)
  return raw.length ? raw : [t]
}

const BIGRAM_SKIP = new Set(['应该', '不该', '可以', '不能', '不会', '不是', '是否', '还是', '一个', '什么', '怎么', '如果', '因为', '所以', '但是', '而且', '就是', '这样', '那样', '没有', '我们', '他们', '这个', '那个', '一定', '真的', '其实', '可能', '需要', '必须', '不要', '只是', '已经', '正在', '之间', '对于', '关于', '以及', '并且', '或者', '还有', '出来', '起来', '上去', '下去'])
function bigramsOf(s: string): string[] {
  const y = String(s ?? '').replace(/[^\u4e00-\u9fa5a-z0-9]/g, '').toLowerCase()
  const out: string[] = []
  for (let i = 0; i < y.length - 1; i++) {
    const g = y.slice(i, i + 2)
    if (!BIGRAM_SKIP.has(g)) out.push(g)
  }
  return out
}
function wordHits(hay: string, needles: string[]): number {
  let s = 0
  needles.forEach((n) => { if (n && n.length >= 2 && hay.includes(n)) s += Math.min(n.length, 4) })
  return s
}

/** 例证语料的 char-bigram IDF：罕见二元组权重高（「骑手」>「教育」） */
let __bgCorpus: string[] | null = null
function bgIdf(g: string): number {
  if (!__bgCorpus) {
    __bgCorpus = PERSON_EX.map((p) => (p.n + ' ' + p.f + ' ' + p.pro + ' ' + p.con + ' ' + p.k.join(' ')).toLowerCase())
  }
  let n = 0
  for (const line of __bgCorpus) if (line.indexOf(g) >= 0) n++
  return n ? 1 / Math.sqrt(n) : 0
}

export interface RankedPerson { p: PersonEntry; sc: number }

/** 例证排序引擎：例证工坊与稿件引擎共用同一套排序（两处结果一致） */
export function rankExamples(t: string): { hits: PersonEntry[]; theme: ThemeEntry | null } {
  const kw = t.toLowerCase()
  const segs = exSegs(t).filter((s) => !STOP.has(s))
  const bg = bigramsOf(t)

  const scored = PERSON_EX.map((p) => {
    const text = (p.n + ' ' + p.f + ' ' + p.pro + ' ' + p.con + ' ' + p.k.join(' ')).toLowerCase()
    let sc = wordHits(kw, p.k.map((k) => k.toLowerCase())) * 3
    const th = THEME_EX.find((x) => x.name === p.theme)
    if (th) {
      sc += wordHits(kw, (th.k || []).map((k) => k.toLowerCase())) * 0.5
      sc += wordHits(kw, (th.kWeak || []).map((k) => k.toLowerCase())) * 0.25
    }
    sc += segs.reduce((a, s) => a + (text.includes(s.toLowerCase()) ? Math.min(s.length, 4) : 0), 0)
    sc += Math.min(4, bg.reduce((a, g) => a + (text.indexOf(g) >= 0 ? bgIdf(g) : 0), 0))
    return { p, sc }
  }).filter((x) => x.sc > 0).sort((a, b) => b.sc - a.sc)

  let theme: ThemeEntry | null = null
  const themeRank = THEME_EX.map((th) => {
    const strong = wordHits(kw, (th.k || []).map((k) => k.toLowerCase()))
    const weak = wordHits(kw, (th.kWeak || []).map((k) => k.toLowerCase()))
    const body = (th.ex || []).join('').toLowerCase()
    const seg = segs.reduce((a, s) => a + ((s.length >= 3 && body.includes(s.toLowerCase())) ? 2 : 0), 0)
    return { th, score: strong * 2 + weak * 0.5 + seg }
  }).filter((x) => x.score > 0).sort((a, b) => b.score - a.score)
  if (themeRank.length) theme = themeRank[0].th

  const hits: PersonEntry[] = []
  const push = (p?: PersonEntry) => { if (p && !hits.includes(p)) hits.push(p) }
  scored.forEach((x) => { if (x.sc >= 3) push(x.p) })
  if (!hits.length && scored.length) push(scored[0].p)

  if (theme) {
    const need = Math.max(0, 6 - hits.length)
    if (need) {
      PERSON_EX.filter((p) => p.theme === theme!.name)
        .map((p) => { const f = scored.find((x) => x.p === p); return { p, sc: f ? f.sc : 0 } })
        .sort((a, b) => (b.sc - a.sc) || (topicHash(t + a.p.n) - topicHash(t + b.p.n)))
        .map((x) => x.p).slice(0, need).forEach(push)
    }
  }
  return { hits, theme }
}

export function topicEvidence(t: string, idx: number): string {
  const R = rankExamples(t)
  if (R.hits.length) {
    const p = R.hits[Math.min(idx, R.hits.length - 1)]
    return '例证：' + p.n + '——' + p.f
  }
  const keys = topicKeys(t)
  return '（本例请自行补一条可查证的事实：围绕「' + (keys[0] || t) + '」检索公开报道或权威数据）'
}

// ---------------- 变体句库与通用立论引擎 ----------------
export const VB: Record<string, string[]> = {
  pDef: ['开宗明义：本题关键概念按辩题语境与日常用法界定；辩题所讨论的「应不应该」，以政策可行且利大于弊为前提。我方立场：{C}。', '开宗明义：本场讨论的是制度选择，不是道德表态；关键概念依日常用法界定，不增不减。我方立场：{C}。', '开宗明义：政策辩的胜负在「需根解损」的闭环上，而非情怀。关键概念照常义界定。我方立场：{C}。'],
  pStd: ['政策辩题的检验框架为「需根解损」：正方须递进证明现状有弊、弊根属于现状、方案能解、利大于弊；反方击穿任一环节即成立。本题争议焦点落在「{F}」。', '判断政策辩题的标准是闭环举证：需——问题真实；根——根属现状；解——方案能解；损——利大于弊。任一环断裂，主张即不成立。本题焦点在「{F}」。', '本题的检验标尺有四步：现状是否有弊、弊根是否在制度、方案是否可行、利弊孰大。争点集中在「{F}」。'],
  pNeed: ['需——现状存在真实而迫切的问题，维持现状的代价正在持续扩大。', '需——问题真实存在，且不会自行消退：拖延本身就是一种选择，而代价由最无力承担的一方支付。', '需——当「照旧」的后果不断累积，「维持现状」已不再是中立选项。'],
  pRoot: ['根——病根在制度与机制本身，个体的零散努力只能治标，无法根除。', '根——这并非执行层面的偏差，而是规则设计留下的结构性缺口。', '根——若根源不在制度，任何个体的努力都只是把问题挪一个位置。'],
  pSolve: ['解与损——我方方案方向明确、技术可行、已有实践先例；收益显著大于成本，且不存在显著更优的替代方案。', '解与损——方案可落地、可检验，执行路径清晰；比较变革的收益与代价，天平明显偏向改变。', '解与损——既有经验证明路径通畅，副作用的量级远小于现状之弊；反对者未能给出更可行的替代。'],
  pNeedNeg: ['需不成立——现状确有瑕疵，但远未到「不可接受」的程度，对方夸大了问题的迫切性。', '需不成立——对方以极端个案代替普遍状况，问题的规模与紧迫性都被放大。', '需不成立——把「可以更好」直接等同于「必须改变」，这一步跳跃缺乏事实支撑。'],
  pRootNeg: ['根不成立——问题的根源不在现行制度，对方的方案也无从触及真正的病灶。', '根不成立——对方诊断错了病因：照此开方，药不对症，副作用却要全社会承担。', '根不成立——把复杂成因单一归咎于制度，是论证上的偷懒，也会误导解决方案。'],
  pSolveNeg: ['解与损不成立——可行性存疑：执行成本、副作用与更优替代都被回避，变革代价大概率超过收益。', '解与损不成立——方案在纸面上成立，在现实中缺少执行条件；而「试行失败」的成本无法回退。', '解与损不成立——对方只证明了「问题存在」，没有证明「此方案能解决」，更没有完成利弊比较。'],
  pValPro: ['变革是为了让制度更好地回应真实的问题——我方愿以「{F}」为起点，推动向好的改变。', '改变从不是冒险的同义词；在「{F}」这件具体的事上，不动才是最大的风险。', '制度的价值在于解决问题，而不是维持自身——这就是我方主张「{C}」的理由。'],
  pValCon: ['审慎不是保守，而是对公共资源的负责——在对方完成举证闭环之前，现状仍是更好的答案。', '改变需要理由，而且是完整的理由；面对「{F}」，对方尚未给出经得起检验的那一份。', '我们并不否认问题，我们否认的是「这样改就能解决」——不该用一次昂贵的试错，赌上所有人的成本。'],
  fDef: ['开宗明义：本题的关键概念应按辩题语境与日常用法界定，不刻意增删条件。我方立场：{C}。', '开宗明义：事实辩先要钉死定义与判准，否则一切争论都是各说各话。我方立场：{C}。', '开宗明义：本题争的是事实，不是立场偏好；关键概念依常识与本义界定。我方立场：{C}。'],
  fStd: ['判断本题的标准在于：概念是否符合本义、机制是否成立、证据是否充分且可复核。核心争论点是「{F}」。', '本题的判准只有三条：定义准确、机制可验、证据可复核。争论的落点在「{F}」。', '衡量本题的尺子：先看定义是否被偷换，再看因果链条是否成立，最后看证据能否被独立复核。焦点是「{F}」。'],
  fMech: ['机制层——我方立场（{C}）成立的关键在事实链条：从「{F}」的成因到结果，证据一致指向我方。', '机制层——把「{F}」放进真实运作中检验，因果链条清晰地落在「{C}」这一侧。', '机制层——就「{F}」而言，决定走向的不是愿望而是机制，而机制的指向与「{C}」一致。'],
  fEv: ['证据层——可复核的数据与案例支持这一判断，而非仅凭直觉或孤例。', '证据层——支撑上述判断的是可查证的事实，而不是被精选出来的个别例证。', '证据层——同类情境反复出现相似结果，这种稳定性本身就是最有力的证据。'],
  fStdPt: ['标准层——对方的判断标准要么循环论证、要么宽以待己；按同一把尺子衡量，事实更支持我方。', '标准层——争的其实是尺子：对方换了尺子才得出另一结论，同一把尺子下我方站得更稳。', '标准层——若把对方的标准反过来用在它自己的论证上，那套说法会立刻失效。'],
  fVal: ['事实不因立场而改变。我方以更完整的证据链与更统一的判断标准，站在「{F}」这一边。', '结论应当服从证据，而不是让证据服从结论——这就是我方坚持「{C}」的原因。', '把定义摆正、把证据摊开，答案自然浮出水面：在「{F}」这件事上，事实站在我方一侧。'],
  vDef: ['开宗明义：本题关键概念按辩题语境与日常用法界定，不刻意增删条件。我方立场：{C}。', '开宗明义：价值辩比的不是对错，而是何者更值得被优先守护；关键概念依常义界定。我方立场：{C}。', '开宗明义：本题要求我们在两种都珍贵的东西之间排序，概念不增不减。我方立场：{C}。'],
  vStd: ['双方立场各有其理，判断标准在于：何者更契合人的长远福祉与社会运行的深层逻辑。价值冲突聚焦于「{F}」。', '比较两种价值，判准必须高于二者：看谁在更长的尺度上、对更多的人成立。争论的核心是「{F}」。', '价值辩的判准是「可普遍化」——一种主张若必须靠牺牲某部分人才能成立，它就已经输了。焦点在「{F}」。'],
  vSelf: ['个人层面——「{C}」更契合个体长远的成长需要：人需要的是可持续的支撑，而非一时的高下。', '个人层面——把镜头拉长到一生，「{C}」给出的答案更经得起回顾，而不只是在当下显得正确。', '个人层面——「{C}」尊重的是人的完整性：它不把人简化成可以被单一口径衡量的对象。'],
  vSoc: ['社会层面——这一主张更经得起机制检验：短期看似对方更高效，长期却透支信任与秩序。', '社会层面——把时间尺度放大，社会运行的深层逻辑所奖励的，正是「{C}」这一侧的选择。', '社会层面——「{C}」不依赖例外与侥幸：它可以被普遍化，而不必靠牺牲一部分人来维持。'],
  vEra: ['时代层面——文明演进的方向正在验证我方：把个体的选择权与尊严放回中心，已是大势所趋。', '时代层面——越是技术加速，越需要「{C}」这样的锚点，否则进步会失去方向。', '时代层面——我们正处在一个旧答案逐渐失效的时刻，「{C}」是对新处境的诚实回应。'],
  vVal: ['我方始终相信：{C}——这不是因为它完美无缺，而是因为它经得起时间与现实的检验。', '{C}——这句话的分量不在漂亮，而在于它是我们愿意长期共处的那条底线。', '我方主张「{C}」，不是因为它更容易，而是因为它更值得。'],
}

export interface EngineResult {
  def: string
  std: string
  pts: string[]
  val: string
  quotes: string[]
  src: string
}

function topicHash(s: string): number {
  let h = 2166136261
  const x = String(s)
  for (let i = 0; i < x.length; i++) { h ^= x.charCodeAt(i); h = Math.imul(h, 16777619) }
  return h >>> 0
}
function pickV(arr: string[], s: string, salt?: string): string {
  return arr[topicHash(String(s) + (salt || '')) % arr.length]
}

/** 通用立论引擎主入口：辩题库命中 → 定制立论；否则模板 + 贴题例证 */
export function engine(topic: string, side: Side, type: TopicType): EngineResult {
  const bank = matchBank(topic)
  if (bank) {
    const s = bank[side]
    return { def: s.def, std: s.std, pts: s.pts.slice(), val: s.val, quotes: s.q.slice(), src: '内置辩题库 · ' + bank.name }
  }
  const claim = claimOf(topic, side)
  const theme = matchTheme(topic)
  const ev = (i: number) => topicEvidence(topic, i)
  const quotes = matchQuotes(topic)
  const keys = topicKeys(topic)
  const focus = keys[0] || topic
  const mk = (arr: string[], salt: string) => {
    const s = pickV(arr, topic, salt)
    return s.replace(/\{C\}/g, claim).replace(/\{F\}/g, focus)
  }
  let def: string, std: string, pts: string[], val: string
  if (type === 'policy') {
    def = mk(VB.pDef, 'd'); std = mk(VB.pStd, 's')
    if (side === 'pro') {
      pts = [mk(VB.pNeed, 'n') + ev(0), mk(VB.pRoot, 'r') + ev(1), mk(VB.pSolve, 'v') + ev(2)]
      val = mk(VB.pValPro, 'V')
    } else {
      pts = [mk(VB.pNeedNeg, 'n') + ev(0), mk(VB.pRootNeg, 'r') + ev(1), mk(VB.pSolveNeg, 'v') + ev(2)]
      val = mk(VB.pValCon, 'V')
    }
  } else if (type === 'fact') {
    def = mk(VB.fDef, 'd'); std = mk(VB.fStd, 's')
    pts = [mk(VB.fMech, 'm') + ev(0), mk(VB.fEv, 'e') + ev(1), mk(VB.fStdPt, 't') + ev(2)]
    val = mk(VB.fVal, 'V')
  } else {
    def = mk(VB.vDef, 'd'); std = mk(VB.vStd, 's')
    pts = [mk(VB.vSelf, 'a') + ev(0), mk(VB.vSoc, 'b') + ev(1), mk(VB.vEra, 'c') + ev(2)]
    val = mk(VB.vVal, 'V')
  }
  return { def, std, pts, val, quotes, src: '通用立论引擎' + (theme ? ' · ' + theme.name + '例证' : '') }
}

// ---------------- 数据三连生成器（纯本地，0 消耗） ----------------

export interface DataPoint {
  /** 命中的原文片段 */
  raw: string
  /** 数字部分 */
  num: string
  /** 数据种类：percent 百分比 / amount 金额规模 / count 计数 / time 年份时段 */
  kind: 'percent' | 'amount' | 'count' | 'time'
}

// 顺序即优先级：带具体单位的计数先于宽口径的金额，避免「3 万件」被当钱
const DATA_PATTERNS: { re: RegExp; kind: DataPoint['kind'] }[] = [
  { re: /\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?\s*个百分点/g, kind: 'percent' },
  // (?<!第) 排除「第 X 条/款」的法条编号——编号不是数据点
  { re: /(?<!第\s?)\d+(?:\.\d+)?\s*万?(?:人|人次|件|篇|所|家|倍|条|集|款)/g, kind: 'count' },
  { re: /\d+(?:\.\d+)?\s*(?:亿|万)?\s*[元块钱]|[¥￥$]\s?\d+(?:\.\d+)?\s*(?:亿|万)?|\d+(?:\.\d+)?\s*(?:亿|万)(?![人件篇所家倍条集款])/g, kind: 'amount' },
  { re: /(?:19|20)\d{2}\s*年/g, kind: 'time' },
]

/** 从一段论点里抽出全部数据点（去重、按出现顺序）。 */
export function extractDataPoints(text: string): DataPoint[] {
  const out: DataPoint[] = []
  const seen = new Set<string>()
  // 法条引用（第 X 条/款/项…）是编号不是数据点——先整体剔除，数字串中段起配
  // 的 lookbehind 堵不住「第 12 条第 2 款」这类连环引用
  const cleaned = text.replace(/第\s?\d+\s*[条款项章节]/g, ' ')
  for (const { re, kind } of DATA_PATTERNS) {
    for (const m of cleaned.matchAll(re)) {
      const raw = m[0].trim()
      if (raw && !seen.has(raw)) {
        seen.add(raw)
        out.push({ raw, num: raw.replace(/[^\d.亿万万元块名人次条篇%¥￥$]/g, ''), kind })
      }
    }
  }
  return out
}

/** 为一个数据点生成「四连问」——基数/口径/来源/去哪查（观摩实战提炼的标准动作）。 */
export function tripleProbe(dp: DataPoint): [string, string, string, string] {
  const subject = dp.raw
  switch (dp.kind) {
    case 'percent':
      return [
        `「${subject}」的基数是多少？分母是谁，算没算上不该算的人？`,
        `「${subject}」的口径是什么——问卷怎么问的、选项怎么设的？`,
        `「${subject}」出自哪份研究？谁做的、样本多大、原文怎么说的？`,
        `去哪查：国家统计局及地方统计公报、学术库（知网/万方）原文、行业白皮书全文——二手转述一律降级为「有报道称」。`,
      ]
    case 'amount':
      return [
        `「${subject}」是总规模还是人均？跟什么比才叫大？`,
        `「${subject}」的钱花在哪、算不算一次性投入？`,
        `「${subject}」的出处是财报、报道还是估算？`,
        `去哪查：巨潮资讯（上市公司公告）、政府采购网、主管部门年度预算公开——财经自媒体的数字一律要回溯到原始文件。`,
      ]
    case 'count':
      return [
        `「${subject}」的统计范围是什么？全国还是局部？`,
        `「${subject}」和基准线比变化了吗——没有对比的计数说明什么？`,
        `「${subject}」的数据来源与采集方式是什么？`,
        `去哪查：主管部门官网发布、行业协会年度报告、裁判文书网（涉案数量）——先找官方口径再找学术口径。`,
      ]
    case 'time':
      return [
        `拿「${subject}」说事，时间点选得有倾向性吗——换一年结论还成立吗？`,
        `「${subject}」之后的数据呢——趋势是延续还是反转？`,
        `「${subject}」那个时点的背景与现在可比吗？`,
        `去哪查：官方修订记录与历年公报对比（同一口径拉长时间轴）、网页存档快照——看数字当时的原始出处是怎么写的。`,
      ]
  }
}

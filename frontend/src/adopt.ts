/**
 * 采纳映射：把一路参谋产出里的一条，翻成「我方论点台账」卡片。
 *
 * **这是唯一的映射来源** —— 界面上「采纳为我方主张」按钮与一致性检测的
 * "新主张"抽取都从这里取（见 `AdvisorColumn.tsx` 与 `App.collectClaims`），
 * 避免两处各写一份而慢慢对不上（同一事实出现两份就是 bug 温床）。
 *
 * 哪几路可采纳见 `ADOPTABLE_KINDS`：反驳手、论证策略师、风险提示员。
 * 质询手给的是"问句"、逻辑审计员给的是"指认"，都不是"我方主张"，
 * 记进台账语义不对，故不纳入。
 *
 * 注意：随提示词包（legal / general）变的是**模型产出**，这里只做机械搬运，
 * 不掺任何领域词 —— 与 `schemas.py` 字段描述中立化是同一条纪律。
 */
import type { AdoptCard, MethodNote, Rebuttal, RiskItem } from './types'

/** 哪些参谋路支持「采纳为我方主张」。 */
export const ADOPTABLE_KINDS = ['rebuttal', 'strategy', 'risk'] as const

export function isAdoptable(kind: string): boolean {
  return (ADOPTABLE_KINDS as readonly string[]).includes(kind)
}

/** 返回 null = 这一条不足以成卡（如缺关键字段），界面就不显示采纳按钮。 */
export function cardFor(kind: string, item: unknown): AdoptCard | null {
  if (kind === 'rebuttal') {
    const r = item as Rebuttal
    const claim = r?.claim?.trim()
    if (!claim) return null
    return {
      claim,
      major_premise: r.major_premise ?? '',
      minor_premise: r.minor_premise ?? '',
      conclusion: r.conclusion ?? '',
      source: 'rebutter',
    }
  }

  if (kind === 'strategy') {
    const m = item as MethodNote
    const our = m?.our_method?.trim()
    if (!our) return null
    // 「我方主张的方法」就是立场本身；对方用的方法作小前提留个出处。
    return {
      claim: `我方主张应以「${our}」为准`,
      major_premise: m.counter ?? '',
      minor_premise: m.opponent_method ? `对方主张「${m.opponent_method.trim()}」` : '',
      conclusion: '',
      source: 'strategist',
    }
  }

  if (kind === 'risk') {
    const x = item as RiskItem
    const risk = x?.risk?.trim()
    if (!risk) return null
    const advice = x.suggestion?.trim()
    // 风险点本身不是"主张"，但它的**应对建议**是 —— 记成"我方主张这样应对"，
    // 才能进「我方已主张」被后续轮次守住；风险点放进大前提（依据）。
    return {
      claim: advice ? `我方主张：${advice}` : `我方须留意风险：${risk}`,
      major_premise: risk,
      minor_premise: x.kind ?? '',
      conclusion: '',
      source: 'risk',
    }
  }

  return null
}

/**
 * `adopt.cardFor` 的单测。
 *
 * 这一层是「按钮能不能点」和「一致性检测抽哪些主张」的**唯一来源**
 * （界面按钮与 collectClaims 都从这里取），所以映射规则错了不会只是"显示难看"，
 * 而是会漏掉或错加一条进我方台账 —— 值得钉死几条边界。
 */
import { describe, expect, it } from 'vitest'
import { ADOPTABLE_KINDS, cardFor, isAdoptable } from '../adopt'

describe('哪些一路可采纳', () => {
  it('反驳手 / 论证策略师 / 风险提示员', () => {
    expect([...ADOPTABLE_KINDS]).toEqual(['rebuttal', 'strategy', 'risk'])
    expect(isAdoptable('rebuttal')).toBe(true)
    // 质询手给问句、逻辑审计员给指认，都不是"我方主张"，不进台账
    expect(isAdoptable('challenger')).toBe(false)
    expect(isAdoptable('logic-auditor')).toBe(false)
  })
})

describe('rebuttal（反驳手）', () => {
  it('有主张就成卡', () => {
    const card = cardFor('rebuttal', {
      claim: '  对方把「AI 生成」等同于「人类创作」  ',
      major_premise: '著作权要求创作出于人的智力判断',
      minor_premise: '',
      conclusion: '故不享有著作权',
    })
    expect(card).toEqual({
      claim: '对方把「AI 生成」等同于「人类创作」',
      major_premise: '著作权要求创作出于人的智力判断',
      minor_premise: '',
      conclusion: '故不享有著作权',
      source: 'rebutter',
    })
  })

  it('主张是空白（模型回了句空串）→ 不成卡，按钮不该亮', () => {
    expect(cardFor('rebuttal', { claim: '   ', major_premise: 'x' })).toBeNull()
    expect(cardFor('rebuttal', {})).toBeNull()
  })
})

describe('strategy（论证策略师）', () => {
  it('我方方法进主张，对方方法留作小前提出处', () => {
    const card = cardFor('strategy', {
      our_method: '利益衡量',
      counter: '支持方主张应激励产出',
      opponent_method: '目的解释',
    })
    expect(card?.claim).toBe('我方主张应以「利益衡量」为准')
    expect(card?.major_premise).toBe('支持方主张应激励产出')
    expect(card?.minor_premise).toBe('对方主张「目的解释」')
    expect(card?.conclusion).toBe('')
    expect(card?.source).toBe('strategist')
  })

  it('没有我方方法 → 不成卡（策略路给不出立场就什么都记不了）', () => {
    expect(cardFor('strategy', { counter: 'x' })).toBeNull()
    expect(cardFor('strategy', { our_method: ' ' })).toBeNull()
  })
})

describe('risk（风险提示员）', () => {
  it('有应对建议就记成"我方主张这样应对"', () => {
    const card = cardFor('risk', { risk: '对方援引第 10 条', kind: '被突袭', suggestion: '要求澄清适用范围' })
    expect(card?.claim).toBe('我方主张：要求澄清适用范围')
    expect(card?.major_premise).toBe('对方援引第 10 条')
    expect(card?.minor_premise).toBe('被突袭')
  })

  it('只有风险点没给建议 → 退化成"须留意"，仍然成卡', () => {
    const card = cardFor('risk', { risk: '可能被追问证据链', kind: '事实' })
    expect(card?.claim).toBe('我方须留意风险：可能被追问证据链')
    expect(card?.major_premise).toBe('可能被追问证据链')
  })

  it('风险点本身空白 → 不成卡', () => {
    expect(cardFor('risk', { risk: '' })).toBeNull()
    expect(cardFor('risk', {})).toBeNull()
  })
})

describe('认不出来的路', () => {
  it('未知 kind 一律 null，绝不硬造一张卡', () => {
    expect(cardFor('whatever', { claim: 'x' })).toBeNull()
    expect(cardFor('', { claim: 'x' })).toBeNull()
    // 连"看着像但不在名单里"的也挡住
    expect(cardFor('rebut', { claim: 'x' })).toBeNull()
  })
})

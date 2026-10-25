import { describe, expect, it } from 'vitest'
import DATA from '../data/prep/debate-data.json'
import {
  ARENA_QUESTIONS, claimOf, detectType, engine, matchBank,
  parseTopic, rankExamples, topicKeys,
} from '../prep/engine'

describe('数据完整性（提取层）', () => {
  it('辩题库 / 主题库 / 人物库 / 金句库 / 攻防题库均非空', () => {
    expect(DATA.BANK.length).toBeGreaterThanOrEqual(18)
    expect(DATA.THEME_EX.length).toBeGreaterThanOrEqual(12)
    expect(DATA.PERSON_EX.length).toBeGreaterThanOrEqual(77)
    expect(DATA.QUOTES.length).toBeGreaterThanOrEqual(55)
    expect(ARENA_QUESTIONS.length).toBeGreaterThanOrEqual(10)
  })
  it('辩题库每条都有完整的双持方材料', () => {
    for (const b of DATA.BANK) {
      expect(b.pro.def).toBeTruthy()
      expect(b.pro.std).toBeTruthy()
      expect(b.pro.pts.length).toBeGreaterThanOrEqual(2)
      expect(b.con.val).toBeTruthy()
    }
  })
  it('攻防题每条都有题型、来源、题面与应对要点', () => {
    for (const q of ARENA_QUESTIONS) {
      expect(q.t).toBeTruthy()
      expect(q.src).toBeTruthy()
      expect(q.q).toBeTruthy()
      expect(q.tip).toBeTruthy()
    }
  })
})

describe('题型判定', () => {
  it('政策 / 价值 / 事实三类', () => {
    expect(detectType('AI 生成内容应不应该强制标注')).toBe('policy')
    expect(detectType('效率与公平哪个更重要')).toBe('value')
    expect(detectType('公元前有没有全球化')).toBe('fact')
  })
})

describe('拆题：任意辩题拆出正反主张', () => {
  it('斜杠式', () => {
    expect(parseTopic('AI 的发展应该/不应该以友善为前提')).toEqual({
      pro: 'AI 的发展应该以友善为前提', con: 'AI 的发展不应该以友善为前提',
    })
  })
  it('该不该', () => {
    const p = parseTopic('高考该不该取消英语')
    expect(p.pro).toBe('高考该取消英语')   // 该不该 → 该/不该（原实现语义）
    expect(p.con).toBe('高考不该取消英语')
  })
  it('还是式（共享比较词尾）', () => {
    const p = parseTopic('效率还是公平更重要')
    expect(p.pro).toBe('效率')              // 原实现：L 无比较词尾时如实返回
    expect(p.con).toBe('公平更重要')
  })
  it('claimOf 双侧可取', () => {
    expect(claimOf('安乐死应不应该合法化', 'pro')).toContain('应该合法化')
    expect(claimOf('安乐死应不应该合法化', 'con')).toContain('不应该合法化')
  })
})

describe('立论引擎', () => {
  it('辩题库命中 → 实录级材料（金钱辩）', () => {
    const r = engine('金钱是万恶之源', 'pro', 'value')
    expect(r.src).toContain('内置辩题库')
    expect(r.def).toContain('钱')
    expect(r.pts.length).toBeGreaterThanOrEqual(2)
  })
  it('未命中 → 通用引擎供料（政策辩含例证引用）', () => {
    const r = engine('外卖骑手差评自由该不该被平台限制', 'pro', 'policy')
    expect(r.src).toContain('通用立论引擎')
    expect(r.def).toContain('外卖骑手差评自由')
    expect(r.pts.join('')).toContain('例证：')
  })
  it('贴题取材：相关辩题拿到相关例证（不含孙中山）', () => {
    const R = rankExamples('外卖骑手差评自由该不该被平台限制')
    expect(R.hits.length).toBeGreaterThan(0)
    expect(R.hits.every((p) => p.n !== '孙中山')).toBe(true)
  })
  it('关键词提取剥掉模态词', () => {
    expect(topicKeys('AI 生成内容应不应该强制标注')).not.toContain('应不应该')
  })
  it('matchBank 大小写不敏感', () => {
    expect(matchBank('金钱是万恶之源吗')).not.toBeNull()
  })
})

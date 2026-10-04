/**
 * 引用状态条与提示词包标签的文案口径（2026-10-04 云端真跑后新增）。
 *
 * 两条都是**真实缺陷的修复**，各有一次实测支撑，所以在这里钉死：
 *
 * 1. **零引用也要显示**。此前条件是 `autoCite.total > 0` 才渲染，
 *    通用辩题下参谋不引法条 ⇒ 状态条整条不出现，用户分不清
 *    「本轮没有引用」与「核验面板坏了」。而核验是纯本地、0 消耗、
 *    几乎不会失败，所以「0 引用」是可信结论。
 * 2. **自由输入要说清没选领域**。手打一道法学题时 `domain` 为空，
 *    后端按「绝不猜」规则落`general` 包（实测产出明显弱于 `legal`），
 *    但界面只显示「提示词包 通用」—— 用户不知道自己能切过去。
 */
import { describe, expect, it } from 'vitest'
import { citeBar, packNote } from '../citeBar'
import type { CitationReport } from '../types'

function rep(over: Partial<CitationReport> = {}): CitationReport {
  return {
    total: 0,
    verified: 0,
    dubious: 0,
    unverified: 0,
    content_suspect: 0,
    match_low: 0.45,
    retriever: 'local-corpus',
    items: [],
    ...over,
  }
}

describe('citeBar', () => {
  it('还没核验（null）⇒ 不渲染', () => {
    expect(citeBar(null)).toBeNull()
  })

  it('零引用也要出现，并说清这是正常的（此前整条不渲染）', () => {
    const bar = citeBar(rep())
    expect(bar).not.toBeNull()
    expect(bar!.text).toContain('本轮无')
    expect(bar!.text).toContain('通用辩题')
    // 零引用不是异常，不该转警示色
    expect(bar!.warn).toBe(false)
    expect(bar!.title).toContain('不是出错')
  })

  it('有引用时报三项计数', () => {
    const bar = citeBar(rep({ total: 3, verified: 2, unverified: 1 }))
    expect(bar!.text).toContain('已核验 2')
    expect(bar!.text).toContain('未核验 1')
    // 没有待查项就不该出现这一段
    expect(bar!.text).not.toContain('引述待查')
    expect(bar!.warn).toBe(false)
  })

  it('存疑数也要报出来（不能只报已核验/未核验，把中间态藏了）', () => {
    const bar = citeBar(rep({ total: 3, verified: 1, dubious: 1, unverified: 1 }))
    expect(bar!.text).toContain('存疑 1')
  })

  it('引述待查 ⇒ 转警示色并单列出来', () => {
    const bar = citeBar(rep({ total: 2, verified: 1, content_suspect: 1 }))
    expect(bar!.text).toContain('引述待查 1')
    expect(bar!.warn).toBe(true)
  })

  it('全0但 total>0（核验跑了、确实没抽到引用）也走"有引用"分支而不是"本轮无"', () => {
    // total 是核验器抽到的引用条数：>0 却全 0 说明报告不一致，宁可如实报数
    const bar = citeBar(rep({ total: 2 }))
    expect(bar!.text).toContain('已核验 0')
    expect(bar!.text).not.toContain('本轮无')
  })
})

describe('packNote', () => {
  it('还没拿到包名 ⇒ 空（不占位）', () => {
    expect(packNote('', 'AI + 法学')).toEqual({ text: '', title: '' })
  })

  it('选了预设辩题 ⇒ 只报包名', () => {
    const n = packNote('法学', 'AI + 法学')
    expect(n.text).toBe('提示词包 法学')
    expect(n.title).toContain('由辩题的「领域」决定')
  })

  it('自由输入（无领域）⇒ 明说没选领域，并告诉用户能切过去', () => {
    const n = packNote('通用', '')
    expect(n.text).toContain('自由输入')
    expect(n.text).toContain('未选领域')
    // 关键：要给出路（从下拉选预设），否则用户只知道自己"没选"却不知道怎么选
    expect(n.title).toContain('下拉')
  })

  it('有领域时不要说教（那会变成噪音）', () => {
    expect(packNote('法学', '法学').title).not.toContain('下拉')
  })
})

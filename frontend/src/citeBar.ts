/**
 * 引用状态条的口径：**界面上那一句"引用 ……"该怎么显示**。
 *
 * 抽成纯函数是为了能测。`App.tsx` 是顶层编排（要 mock 一整条 SSE 链），
 * 而这里恰恰是"错了用户会误解"的地方：2026-10-04 云端真跑之前，
 * 零引用时状态条**整条不渲染**—— 用户在通用辩题下看到的是"什么都没有"，
 * 分不清是"本轮没引用"还是"核验面板坏了"。
 *
 * 两条不变的口径：
 * 1. **零引用也要出现**。核验是纯本地计算、0 消耗、几乎不会失败，
 *    所以"0 引用"是一个可信的结论，值得占一个位置说清，而不是留白。
 * 2. **不自动降级成"存疑/未核验"**。裁定权在人（见 `citations.py` 模块头），
 *    这里只如实报数。
 */
import type { CitationReport } from './types'

export interface CiteBar {
  /** 无引用时给"这是正常的"一句，不让人以为坏了。 */
  text: string
  /** 引述与原文对不上时置true（转警示色）。 */
  warn: boolean
  /** 鼠标悬停说明：把"这个数字是什么意思 / 为什么是0"讲清。 */
  title: string
}

/** 由本轮辩题领域决定的提示词包，为空表示还没拿到后端回传。 */
export function packNote(packLabel: string, topicDomain: string): {
  text: string
  title: string
} {
  if (!packLabel) return { text: '', title: '' }
  if (topicDomain) {
    return {
      text: `提示词包 ${packLabel}`,
      title: '本轮参谋提示词用的是这个领域包，由辩题的「领域」决定',
    }
  }
  // 自由输入没有 domain，后端按"绝不猜"规则落到默认包。静默fallback 会让
  // 用户以为拿到的是法学建议（实测：法学题手打时拿到 general 包，产出明显更弱）。
  return {
    text: `提示词包 ${packLabel} · 自由输入，未选领域`,
    title:
      '自由输入的辩题没有「领域」，后端按规则落到默认包（不猜）。'
      + '若这道题属于某个有专用包的领域，从「① 辩题」下拉里选一条预设即可切过去',
  }
}

/**
 * 引用状态条。`report` 为 null（还没核验 / 后端未连通）时返回 null = 不渲染。
 */
export function citeBar(report: CitationReport | null): CiteBar | null {
  if (!report) return null
  if (report.total === 0) {
    return {
      text: '引用 本轮无（通用辩题不引法条）',
      warn: false,
      title:
        '本轮参谋没有引用任何法条。引用核验只对法源引用有意义——通用辩题属正常，不是出错',
    }
  }
  return {
    text:
      `引用 已核验 ${report.verified} · 存疑 ${report.dubious} · 未核验 ${report.unverified}`
      + (report.content_suspect > 0 ? ` · 引述待查 ${report.content_suspect}` : ''),
    warn: report.content_suspect > 0,
    title: '分析完成后自动核验了本轮引用（纯本地，0 消耗）',
  }
}

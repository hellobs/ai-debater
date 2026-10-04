/** 现场工作状态的持久化 —— 存在**本机浏览器**里，刷新/误关标签页后原样恢复。
 *
 * 为什么需要它
 * ------------
 * 辩论现场的输入是「资产」：辩题、立场、刚收音进来的对方发言，都是现场
 * 一条条攒出来的。此前它们只活在 React state 里——误按 F5、浏览器崩一下，
 * 全部清零，而对方的发言不会再说一遍。
 *
 * 会话本身在后端 SQLite（ledger.db）里**一直都在**；这里补的是「输入区与
 * 会话的关联」：把 sessionId 一起存下来，刷新后自动接回台账与导出。
 *
 * 这次扩了**参谋产出**
 * --------------------
 * 起初只存输入，理由是「产出可重算、台账才是事实来源」。但点一次分析是 5 次上游调用，
 * 刷新一下就归零、想再看必须重跑一遍——成本后果太实在。于是把上一轮的 5 路产出与
 * 整轮耗时一并存，恢复时直接回填界面。会话仍是权威（可导出、可跨机），这份只是
 * 「别让人白跑一趟」的本地缓存。
 *
 * 边界如实说
 * ----------
 * - `opponentText` 明文存 localStorage（与 upstreamStore 同一信任模型：
 *   本机工具，本机可读，不上传第三方，不假装加密）。
 * - 多标签页同开时后者覆盖前者——与上游配置的存储同一取舍，不为此加锁。
 */

import type { AdvisorResult } from './types'

export interface LiveState {
  topic: string
  ourSide: string
  opponentText: string
  selectedTopicId: string
  budget: number
  sessionId: string | null
  /** 用户是否手动调过时间预算（恢复时据此决定要不要让健康检查覆盖它） */
  budgetTouched: boolean
  /** 上一轮参谋产出（5 路）。恢复后直接回填界面，省掉重跑的 5 次上游调用 */
  results: Record<string, AdvisorResult> | null
  /** 上一轮整轮总耗时（秒），恢复后 board-meta 照旧显示 */
  totalLatency: number | null
  savedAt: number
}

const STORE_KEY = 'debater.liveState.v1'

/** 三个边界，讲给下一个改这个文件的人听
 * ----------------------------------
 * - 产出**不兜底**：后端一升级、名册或提示词包一改，缓存里的 payload 结构就可能过期。
 *   恢复时按路名逐条回填，认不出来的路就是空着（重跑一次即可），不会被旧结构渲染歪。
 * - 体积有上限：超了只存输入、不存产出，不拿 localStorage 冒险（配额通常 5MB）。
 * - 隐私模式写不进去时静默跳过，不阻断主流程。
 */
/** 产出快照的体积上限（字节） */
const MAX_RESULTS_BYTES = 1_200_000

export function loadLiveState(): LiveState | null {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    // 字段齐全才认：格式升级后旧快照直接丢弃，不猜
    if (
      data &&
      typeof data === 'object' &&
      typeof data.topic === 'string' &&
      typeof data.opponentText === 'string'
    ) {
      // 产出只按"路名 → 对象"的粗形状收下：细结构由渲染侧按路名逐条用，认不出就空着
    const results =
      data.results && typeof data.results === 'object' ? data.results : null
    return { ...(data as LiveState), results } as LiveState
    }
    return null
  } catch {
    return null
  }
}

export function saveLiveState(state: LiveState): void {
  // 先按原样写；产出太大时才降级为「只存输入」——宁可少存，也不把 localStorage 塞爆
  let payload: LiveState = state
  if (state.results) {
    let bytes = 0
    try {
      bytes = JSON.stringify(state).length
    } catch {
      return
    }
    if (bytes > MAX_RESULTS_BYTES) {
      payload = { ...state, results: null }
    }
  }
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(payload))
  } catch {
    /* 隐私模式下写不进去；或者配额满了——都不阻断主流程 */
  }
}

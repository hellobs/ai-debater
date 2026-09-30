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
 * 边界如实说
 * ----------
 * - `opponentText` 明文存 localStorage（与 upstreamStore 同一信任模型：
 *   本机工具，本机可读，不上传第三方，不假装加密）。
 * - 多标签页同开时后者覆盖前者——与上游配置的存储同一取舍，不为此加锁。
 */

export interface LiveState {
  topic: string
  ourSide: string
  opponentText: string
  selectedTopicId: string
  budget: number
  sessionId: string | null
  /** 用户是否手动调过时间预算（恢复时据此决定要不要让健康检查覆盖它） */
  budgetTouched: boolean
  savedAt: number
}

const STORE_KEY = 'debater.liveState.v1'

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
      return data as LiveState
    }
    return null
  } catch {
    return null
  }
}

export function saveLiveState(state: LiveState): void {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(state))
  } catch {
    /* 隐私模式下写不进去；不阻断主流程 */
  }
}

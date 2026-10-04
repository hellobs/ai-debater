/**
 * `liveStateStore` 的单测：现场状态恢复的老本行是「不许因为存储坏了就崩」。
 *
 * 三条例行：坏 JSON / 字段形状不对 → 当作没恢复过（宁可空着，也不拿旧结构渲染）；
 * 产出体积超上限 → 降级成"只存输入"，输入这一半才是丢不起的。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { loadLiveState, saveLiveState, type LiveState } from '../liveStateStore'
import { installLocalStorage, LIVE_KEY } from './helpers'

afterEach(() => {
  vi.unstubAllGlobals()
})

function state(over: Partial<LiveState> = {}): LiveState {
  return {
    topic: 'AI 生成内容是否应享有著作权',
    ourSide: '正方',
    opponentText: '对方刚说的内容',
    selectedTopicId: 'ai-copyright',
    budget: 20,
    sessionId: null,
    budgetTouched: false,
    results: null,
    totalLatency: null,
    savedAt: 1,
    ...over,
  }
}

describe('恢复时的容错', () => {
  it('没存过 → null', () => {
    installLocalStorage()
    expect(loadLiveState()).toBeNull()
  })

  it('坏 JSON → null，不冒泡', () => {
    installLocalStorage({ [LIVE_KEY]: '{oops' })
    expect(() => loadLiveState()).not.toThrow()
    expect(loadLiveState()).toBeNull()
  })

  it('topic 不是字符串（旧快照/被别的程序改过）→ 整份丢弃，不猜', () => {
    installLocalStorage({ [LIVE_KEY]: '{"topic":123,"opponentText":"x"}' })
    expect(loadLiveState()).toBeNull()
  })

  it('只有 opponentText 没有 topic → 也认不出来（两份都要是字符串）', () => {
    installLocalStorage({ [LIVE_KEY]: '{"topic":null,"opponentText":"x"}' })
    expect(loadLiveState()).toBeNull()
  })
})

describe('正常往返', () => {
  it('输入区照原样回来', () => {
    const mem = installLocalStorage()
    saveLiveState(state({ topic: 'A', opponentText: 'B', sessionId: 'sid-1', budget: 45 }))
    const back = loadLiveState()
    expect(back?.topic).toBe('A')
    expect(back?.opponentText).toBe('B')
    expect(back?.sessionId).toBe('sid-1')
    expect(back?.budget).toBe(45)
    expect(back?.results).toBeNull()
    expect(mem.raw[LIVE_KEY]).not.toContain('undefined')
  })

  it('写不进去（隐私模式）→ 静默跳过，不抛', () => {
    vi.unstubAllGlobals()
    vi.stubGlobal('localStorage', {
      getItem: () => null,
      setItem: () => {
        throw new Error('quota')
      },
      removeItem: () => {},
    })
    expect(() => saveLiveState(state())).not.toThrow()
    expect(loadLiveState()).toBeNull()
  })
})

describe('体积上限：宁可少存，也不把 localStorage 塞爆', () => {
  it('产出太大 → 降级成只存输入，topic / opponentText 保住', () => {
    const mem = installLocalStorage()
    const huge = { advisor: 'rebuttal', payload: [{ claim: 'x'.repeat(1_400_000) }] }
    saveLiveState(state({ results: { rebuttal: huge as never } }))
    const raw = mem.raw[LIVE_KEY] ?? ''
    expect(raw).toContain('AI 生成内容是否应享有著作权') // 输入还在
    expect(raw).not.toContain('x'.repeat(100)) // 产出被整段丢掉了
    const back = loadLiveState()
    expect(back?.results).toBeNull()
    expect(back?.opponentText).toBe('对方刚说的内容')
  })

  it('产出不大 → 照原样存回来', () => {
    installLocalStorage()
    const results = {
      rebuttal: { advisor: 'rebuttal', status: 'ok', payload: [{ claim: '一句话主张' }] },
    } as never
    saveLiveState(state({ results, totalLatency: 9.74 }))
    const back = loadLiveState()
    expect(back?.totalLatency).toBe(9.74)
    expect(back?.results).toEqual(results)
  })
})

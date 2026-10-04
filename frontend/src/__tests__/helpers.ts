/**
 * 测试用的 localStorage 替身。
 *
 * 这两个 store 都只在**调用时**摸 `localStorage`（不在 import 期读），
 * 所以每个用例自己插一个内存实现就够 —— 不必为此拉 jsdom（少一个依赖），
 * 而且"存储被禁用 / 写不进去"这条路我们得自己能造出来。
 */
import { vi } from 'vitest'

/** 两个 store 用的键。从这里导出去，测试里就不用再抄一遍字符串。 */
export const STORE_KEY = 'debater.upstreams.v1'
export const LAST_KEY = 'debater.upstream.last.v1'
export const LIVE_KEY = 'debater.liveState.v1'

export interface MemStorage {
  getItem: (k: string) => string | null
  setItem: (k: string, v: string) => void
  removeItem: (k: string) => void
  /** 断言用：原始文本，能查"到底写没写进去"（密钥这类事要验到字节） */
  raw: Record<string, string>
}

/** 插一个内存 localStorage；返回值能读到原始内容，供密钥类断言使用。 */
export function installLocalStorage(seed: Record<string, string> = {}): MemStorage {
  const map: Record<string, string> = { ...seed }
  const mem: MemStorage = {
    getItem: (k) => (k in map ? map[k] : null),
    setItem: (k, v) => {
      map[k] = String(v)
    },
    removeItem: (k) => {
      delete map[k]
    },
    raw: map,
  }
  vi.stubGlobal('localStorage', {
    getItem: mem.getItem,
    setItem: mem.setItem,
    removeItem: mem.removeItem,
    clear: () => {
      for (const k of Object.keys(map)) delete map[k]
    },
    key: (i: number) => Object.keys(map)[i] ?? null,
    get length() {
      return Object.keys(map).length
    },
  })
  return mem
}

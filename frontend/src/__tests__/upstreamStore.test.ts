/**
 * `upstreamStore` 的纯函数单测（体检第四轮：前端此前零自动化测试）。
 *
 * 重点测**密钥到底有没有落进本机存储** —— 这是拍板「默认不存、显式勾选才存」
 * 的落点，光看界面看不出来：一个字段被传了空串，和一个字段根本没出现，
 * 在界面上都显示成"没记住"。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  clearAll,
  findSaved,
  getLast,
  loadSaved,
  removeConfig,
  saveConfig,
  toPatch,
} from '../upstreamStore'
import { installLocalStorage, STORE_KEY } from './helpers'

afterEach(() => {
  vi.unstubAllGlobals()
})

const base = { kind: 'openai', base_url: 'https://api.example.com/v1', model: 'm' }

describe('saveConfig 的默认：密钥不落本机存储', () => {
  it('不勾"记住密钥"时不写 api_key 字段', () => {
    const mem = installLocalStorage()
    saveConfig({ name: 'A', ...base })
    const list = loadSaved()
    expect(list).toHaveLength(1)
    expect(list[0].api_key).toBe('')
    // 验到字节：存储里根本搜不到这把密钥
    expect(mem.raw[STORE_KEY]).not.toContain('sk-')
  })

  it('勾了"记住密钥"且填了密钥才存明文，而且存得下来', () => {
    const mem = installLocalStorage()
    saveConfig({ name: 'B', ...base, api_key: 'sk-live-1', remember_key: true })
    expect(findSaved('B')?.api_key).toBe('sk-live-1')
    // 必须落到 localStorage 里（raw 里能看到这把），否则"记住"只是界面上一句话
    expect(mem.raw[STORE_KEY]).toContain('sk-live-1')
  })

  it('勾了但没重填：沿用这份已有的那把（改个模型不该洗掉密钥）', () => {
    installLocalStorage()
    saveConfig({ name: 'B', ...base, api_key: 'sk-live-1', remember_key: true })
    saveConfig({ name: 'B', ...base, model: 'm2', remember_key: true })
    expect(findSaved('B')?.api_key).toBe('sk-live-1')
    expect(findSaved('B')?.model).toBe('m2')
  })

  it('取消勾选后保存：把这份已存的密钥清掉（不再"记住"）', () => {
    const mem = installLocalStorage()
    saveConfig({ name: 'B', ...base, api_key: 'sk-live-1', remember_key: true })
    saveConfig({ name: 'B', ...base, remember_key: false })
    expect(findSaved('B')?.api_key).toBe('')
    expect(mem.raw[STORE_KEY]).not.toContain('sk-live-1')
  })

  it('同名覆盖只动那一条，别的配置不受牵连', () => {
    installLocalStorage()
    saveConfig({ name: 'A', ...base, api_key: 'sk-a', remember_key: true })
    saveConfig({ name: 'B', ...base })
    saveConfig({ name: 'A', ...base, model: 'm2', remember_key: true })
    expect(findSaved('A')?.model).toBe('m2')
    expect(findSaved('A')?.api_key).toBe('sk-a')
    expect(findSaved('B')?.api_key).toBe('')
  })
})

describe('toPatch：空密钥绝不能变成"清空后端那把"', () => {
  it('没记住密钥时不带 api_key 字段', () => {
    const patch = toPatch({ name: 'A', ...base, api_key: '', saved_at: 0 })
    expect('api_key' in patch).toBe(false)
    expect(patch).toEqual({ kind: 'openai', base_url: 'https://api.example.com/v1', model: 'm' })
  })

  it('记住了密钥就照实带上（后端才拿得到）', () => {
    const patch = toPatch({ name: 'A', ...base, api_key: 'sk-x', saved_at: 0 })
    expect(patch.api_key).toBe('sk-x')
  })
})

describe('存储被搞坏时不该让界面崩', () => {
  it('坏 JSON → 当作没存过', () => {
    installLocalStorage({ [STORE_KEY]: '{oops' })
    expect(loadSaved()).toEqual([])
  })

  it('存的不是数组 → 当作没存过', () => {
    installLocalStorage({ [STORE_KEY]: '{"not":"an array"}' })
    expect(loadSaved()).toEqual([])
  })

  it('localStorage 直接抛（隐私模式）→ 当作没存过，不冒泡', () => {
    vi.unstubAllGlobals()
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('denied')
      },
      setItem: () => {
        throw new Error('denied')
      },
      removeItem: () => {},
    })
    expect(loadSaved()).toEqual([])
    expect(() => saveConfig({ name: 'A', ...base })).not.toThrow()
  })
})

describe('清除与"上次用过那份"', () => {
  it('removeConfig 删掉指定那条；删的是当前那条就一起摘掉 last', () => {
    installLocalStorage()
    saveConfig({ name: 'A', ...base })
    saveConfig({ name: 'B', ...base })
    expect(getLast()).toBe('B')
    removeConfig('B')
    expect(getLast()).toBeNull()
    expect(loadSaved().map((c) => c.name)).toEqual(['A'])
  })

  it('clearAll 清空全部配置与 last，一个键都不留', () => {
    const mem = installLocalStorage()
    saveConfig({ name: 'A', ...base, api_key: 'sk-a', remember_key: true })
    clearAll()
    expect(loadSaved()).toEqual([])
    expect(getLast()).toBeNull()
    expect(Object.keys(mem.raw)).toEqual([])
  })
})

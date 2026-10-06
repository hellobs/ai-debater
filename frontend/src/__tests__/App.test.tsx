/**
 * @vitest-environment jsdom
 *
 * 开机时**上游以服务端为准**（App.tsx 的对齐 effect）。
 *
 * 为什么这条要测：原实现是"开机自动把本机上次那份配置推给后端"，看着方便，
 * 实际是**每打开一次界面就改一次后端**。实测 2026-10-06：上次用的是本机
 * Ollama，于是打开界面就把配好的云端悄悄切回去，而界面上看不出是谁切的。
 * 浏览器里的配置只该在用户显式选择时生效。
 *
 * 另一头也要守住：后端**确实没有**上游时（首次部署 / 还没配 `.env`），
 * 仍要用本机那份兜底 —— 否则用户每次都得重填地址与密钥。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'

import { installLocalStorage } from './helpers'
import { saveConfig } from '../upstreamStore'
import type { HealthInfo, UpstreamInfo } from '../types'

const CLOUD: UpstreamInfo = {
  kind: 'anthropic',
  base_url: 'https://api.deepseek.com/anthropic',
  model: 'deepseek-flash',
  key_set: true,
  mavis_base_url: 'http://127.0.0.1:8010/bridge/v1',
  host: 'api.deepseek.com',
}

const HEALTH: HealthInfo = {
  ok: true,
  brand: '辩手参谋台',
  version: '9.9.9',
  model: 'deepseek-flash',
  bridge: 'http://127.0.0.1:8010/bridge/v1',
  upstream_configured: true,
  budget_s: 30,
  advisors: [
    { name: 'rebuttal', label: '反驳手', kind: 'rebuttal', domain: '' },
    { name: 'strategy', label: '论证策略师', kind: 'strategy', domain: '' },
  ],
}

// vi.mock 工厂会被提升，必须用 vi.hoisted 在同一处造出这些桩
const api = vi.hoisted(() => ({
  fetchUpstream: vi.fn(async () => ({
    ok: true,
    upstream: { kind: 'ollama', base_url: '', model: '', key_set: false, mavis_base_url: '', host: '' },
    kinds: ['ollama', 'openai', 'anthropic'],
  })),
  setUpstream: vi.fn(async () => ({})),
  fetchHealth: vi.fn(async () => ({})),
  fetchModels: vi.fn(async () => ({ ok: true, models: [], error: '' })),
  fetchTopics: vi.fn(async () => []),
  listSessions: vi.fn(async () => []),
  fetchLatestCitations: vi.fn(async () => ({ reports: [] })),
  knowledgeStatus: vi.fn(async () => ({ files: 0, chunks: 0 })),
  uploadKnowledge: vi.fn(async () => ({ ok: true, chunks: 0 })),
  // 挂载不调到的：给出空实现只为让 import 成立
  addCard: vi.fn(),
  checkConsistency: vi.fn(),
  deleteCard: vi.fn(),
  deleteTopic: vi.fn(),
  fetchSession: vi.fn(),
  patchCard: vi.fn(),
  deleteSession: vi.fn(),
  saveTopic: vi.fn(),
  verifyCitations: vi.fn(),
  streamAnalyze: vi.fn(),
}))

vi.mock('../api', () => api)

const App = (await import('../App')).default

/** 往本机存一份"上次用过"的配置（与用户点过「保存」等价）。 */
function seedSaved() {
  installLocalStorage()
  saveConfig({ name: '本机 Ollama · 127.0.0.1:11434', kind: 'ollama', base_url: 'http://127.0.0.1:11434/v1', model: 'qwen3:8b' })
}

describe('开机对齐上游', () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockClear()
    api.fetchHealth.mockResolvedValue(HEALTH as never)
    api.fetchModels.mockResolvedValue({ ok: true, models: ['deepseek-flash'], error: '' } as never)
  })

  afterEach(() => cleanup())

  it('服务端已有上游时，不把本机上次那份推回去', async () => {
    seedSaved()
    api.fetchUpstream.mockResolvedValue({ ok: true, upstream: CLOUD, kinds: ['ollama', 'openai', 'anthropic'] } as never)

    render(<App />)

    await waitFor(() => expect(api.fetchUpstream).toHaveBeenCalled())
    expect(api.setUpstream).not.toHaveBeenCalled()
  })

  it('服务端没有上游时，用本机那份兜底', async () => {
    seedSaved()
    api.fetchUpstream.mockResolvedValue({
      ok: true,
      upstream: { kind: 'ollama', base_url: '', model: '', key_set: false, mavis_base_url: '', host: '' },
      kinds: ['ollama', 'openai', 'anthropic'],
    } as never)

    render(<App />)

    await waitFor(() => expect(api.setUpstream).toHaveBeenCalled())
    expect(api.setUpstream).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'ollama',
      base_url: 'http://127.0.0.1:11434/v1',
      model: 'qwen3:8b',
    }))
  })
})

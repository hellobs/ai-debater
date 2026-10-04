/**
 * @vitest-environment jsdom
 *
 * SettingsPanel 的组件级测试。
 *
 * 只覆盖**新增/高风险**的用户可见行为，都是"错了会烧钱或丢数据"的那类：
 *  1. ⑦ 本机台账会话：列得出来、逐条能删、删的那条进入「删除中…」并锁住全表；
 *  2. ⑤ 顶部那句「重启后端会回到 .env 初值」与提交按钮下方「点一次 = N 次上游调用」；
 *  3. 密钥勾选框：默认不勾 ⇒ 存下来的配置里**搜不到**那把 key（字节级断言）；
 *  4. 「应用」时空密钥不带 `api_key` 字段（后端 `None`=不动 / `''`=清空）。
 *
 * 刻意不测：视觉样式、动画、录音（`useRecorder` 挂载期不碰麦克风，只在真点
 * 「开始收音」时才申请权限，所以组件能安全挂载）。`../api` 整个 mock 掉——组件
 * 挂载时只调一次 `knowledgeStatus()`，不引它就得在测试里造 fetch。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ComponentProps } from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import { installLocalStorage, STORE_KEY, type MemStorage } from './helpers'
import type { HealthInfo, SessionRow, Topic, UpstreamInfo } from '../types'
import SettingsPanel from '../components/SettingsPanel'

// 组件只 import 了 `knowledgeStatus` / `uploadKnowledge` 两个函数。
vi.mock('../api', () => ({
  knowledgeStatus: vi.fn(async () => ({ files: 0, chunks: 0 })),
  uploadKnowledge: vi.fn(async () => ({ ok: true, chunks: 0 })),
}))

const SECRET = 'sk-do-not-store-me'

const HEALTH: HealthInfo = {
  ok: true,
  brand: '辩手参谋台',
  version: '9.9.9',
  model: 'qwen3:8b',
  bridge: 'http://127.0.0.1:8010/bridge/v1',
  upstream_configured: true,
  budget_s: 20,
  advisors: [
    { name: 'rebuttal', label: '反驳手', kind: 'rebuttal', domain: '' },
    { name: 'strategy', label: '论证策略师', kind: 'strategy', domain: '' },
  ],
}

const UPSTREAM: UpstreamInfo = {
  kind: 'openai',
  base_url: 'https://gateway.example.com/v1',
  model: 'deepseek-chat',
  key_set: true,
  mavis_base_url: 'https://gateway.example.com/v1',
  host: 'gateway.example.com',
}

const SESSIONS: SessionRow[] = [
  { id: 's-1', topic: 'AI 生成内容是否应享有著作权', our_side: '正方', created_at: '2026-10-04 15:02' },
  { id: 's-2', topic: '', our_side: '反方', created_at: '2026-10-04 16:40' },
]

type Props = ComponentProps<typeof SettingsPanel>

/** 一份能直接喂给组件的 props；回调默认 noop，用到哪个覆盖哪个。 */
function makeProps(over: Partial<Props> = {}): Props {
  const noop = () => {}
  return {
    topic: 'AI 生成内容是否应享有著作权',
    ourSide: '正方',
    opponentText: '对方说 AI 作品不是人创作，所以不该有著作权。',
    running: false,
    advisorCount: 5,
    sessionId: 's-1',
    budget: 20,
    health: HEALTH,
    healthErr: null,
    onRecheck: async () => {},
    topics: [] as Topic[],
    selectedTopicId: '',
    onSelectTopic: noop,
    onSaveTopic: noop,
    onDeleteTopic: noop,
    saving: false,
    topicMsg: '',
    onTopic: noop,
    onSide: noop,
    onOpponent: noop,
    onBudget: noop,
    onSubmit: noop,
    onReset: noop,
    upstream: UPSTREAM,
    kinds: ['ollama', 'openai', 'anthropic'],
    models: [],
    modelsErr: '',
    modelsFrom: null,
    onApplyUpstream: async () => null,
    onRefreshModels: async () => {},
    sessions: SESSIONS,
    sessionListErr: '',
    deletingSessionId: null,
    onRefreshSessions: noop,
    onDeleteSession: noop,
    ...over,
  }
}

let mem: MemStorage

beforeEach(() => {
  // 组件里的 localStorage 用内存替身：能读到原始文本做字节级断言（密钥那几例），
  // 也能自己造出"存储写不进去"这条路。jsdom 自带的那份满足不了前一条。
  mem = installLocalStorage()
  // window.confirm 只在「清除全部」时用；默认答"不"，免得用例被弹窗卡住。
  vi.stubGlobal('confirm', vi.fn(() => false))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

/** 切到某个分区（导航是 role=tablist 里的三个 tab；「服务状态」带告警点时名字里多个 `!`）。 */
function openTab(label: string) {
  fireEvent.click(screen.getByRole('tab', { name: new RegExp(label) }))
}

function sessionItems(): HTMLElement[] {
  return [...document.querySelectorAll('.session-items li')] as HTMLElement[]
}

describe('⑦ 本机台账会话', () => {
  it('列出最近会话：辩题、立场、时间都摆出来，空辩题有兜底说法', () => {
    render(<SettingsPanel {...makeProps()} />)
    openTab('服务状态')

    const items = sessionItems()
    expect(items).toHaveLength(2)
    expect(items[0].textContent).toContain('AI 生成内容是否应享有著作权')
    expect(items[0].textContent).toContain('正方')
    expect(items[0].textContent).toContain('2026-10-04 15:02')
    expect(items[1].textContent).toContain('(无辩题)')
    expect(items[1].textContent).toContain('反方')
  })

  it('后端没连通时不摆这个块（那时候整页已经另有报错）', () => {
    render(<SettingsPanel {...makeProps({ health: null, healthErr: 'ECONNREFUSED' })} />)
    openTab('服务状态')
    expect(screen.queryByText('⑦ 本机台账会话')).toBeNull()
  })

  it('点某条的「删除」只把那一条的 id 交出去', () => {
    const onDeleteSession = vi.fn()
    render(<SettingsPanel {...makeProps({ onDeleteSession })} />)
    openTab('服务状态')

    const items = sessionItems()
    fireEvent.click(within(items[1]).getByRole('button', { name: '删除' }))

    expect(onDeleteSession).toHaveBeenCalledTimes(1)
    expect(onDeleteSession).toHaveBeenCalledWith('s-2')
  })

  it('正在删的那条显示「删除中…」并禁用；此时全表按钮都锁住（防并发二次删除）', () => {
    const onDeleteSession = vi.fn()
    render(<SettingsPanel {...makeProps({ deletingSessionId: 's-2', onDeleteSession })} />)
    openTab('服务状态')

    const items = sessionItems()
    const busy = within(items[1]).getByRole('button', { name: '删除中…' })
    expect(busy).toHaveProperty('disabled', true)
    expect(within(items[0]).getByRole('button', { name: '删除' })).toHaveProperty('disabled', true)

    fireEvent.click(busy)
    expect(onDeleteSession).not.toHaveBeenCalled()
  })

  it('分析进行中不许删也不许刷新（避免把正在写的会话从底下抽走）', () => {
    render(<SettingsPanel {...makeProps({ running: true })} />)
    openTab('服务状态')
    expect(within(sessionItems()[0]).getByRole('button', { name: '删除' })).toHaveProperty('disabled', true)
    expect(screen.getByRole('button', { name: '刷新' })).toHaveProperty('disabled', true)
  })

  it('空列表给一句去处；拉取失败把原因摆出来', () => {
    const { unmount } = render(<SettingsPanel {...makeProps({ sessions: [] })} />)
    openTab('服务状态')
    expect(screen.getByText(/还没有会话/)).toBeTruthy()
    unmount()

    render(<SettingsPanel {...makeProps({ sessions: [], sessionListErr: '台账打不开：database is locked' })} />)
    openTab('服务状态')
    expect(screen.getByText(/database is locked/)).toBeTruthy()
  })

  it('「刷新」把回调交出去', () => {
    const onRefreshSessions = vi.fn()
    render(<SettingsPanel {...makeProps({ onRefreshSessions })} />)
    openTab('服务状态')
    fireEvent.click(screen.getByRole('button', { name: '刷新' }))
    expect(onRefreshSessions).toHaveBeenCalledTimes(1)
  })
})

describe('⑤ 把代价和「重启失效」摆在按钮旁边', () => {
  it('顶部直说上游只驻留内存、重启回 .env 初值', () => {
    render(<SettingsPanel {...makeProps()} />)
    openTab('模型与上游')
    const warn = document.querySelector('.warn-block')
    expect(warn?.textContent).toContain('上游只驻留后端内存')
    expect(warn?.textContent).toContain('.env')
  })

  it('提交按钮下方写清一次分析要花几次调用、哪些不计费', () => {
    render(<SettingsPanel {...makeProps({ advisorCount: 5 })} />)
    const hint = screen.getByText(/点一次 = 5 路并行/)
    expect(hint.textContent).toContain('5 次上游调用')
    expect(hint.textContent).toContain('超时的那几路照样计费')
    expect(hint.textContent).toContain('探测')
  })

  it('路数不是 5 时文案跟着变（别写死"五路"）', () => {
    render(<SettingsPanel {...makeProps({ advisorCount: 2 })} />)
    expect(screen.getByText(/点一次 = 2 路并行 = 2 次上游调用/)).toBeTruthy()
  })

  it('参谋全停用时按钮禁用并说清原因（提交必然空转）', () => {
    const onSubmit = vi.fn()
    render(<SettingsPanel {...makeProps({ advisorCount: 0, onSubmit })} />)
    const btn = screen.getByRole('button', { name: '生成参谋建议' })
    expect(btn).toHaveProperty('disabled', true)
    fireEvent.click(btn)
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByText(/没有可用参谋/)).toBeTruthy()
  })
})

describe('密钥默认不存本机', () => {
  /** 填好一份能保存的配置。`key` 空 = 不碰密钥框。 */
  function fillForm(key: string) {
    fireEvent.change(screen.getByPlaceholderText('https://api.example.com/v1'), {
      target: { value: 'https://gateway.example.com/v1' },
    })
    fireEvent.change(screen.getByPlaceholderText('模型名（可手填）'), {
      target: { value: 'deepseek-chat' },
    })
    if (key) {
      fireEvent.change(screen.getByPlaceholderText('API key'), { target: { value: key } })
    }
  }

  const saveBtn = () => screen.getByRole('button', { name: '保存' })

  /** 形态下拉没有 label，按"选项里带得上前缀的那个 select"认它。 */
  function kindSelect(): HTMLSelectElement {
    const hit = [...document.querySelectorAll('select')].find((s) =>
      [...s.options].some((o) => o.textContent?.includes('本机 Ollama')),
    )
    if (!hit) throw new Error('没找到形态下拉')
    return hit as HTMLSelectElement
  }

  it('勾选框默认不勾', () => {
    render(<SettingsPanel {...makeProps()} />)
    openTab('模型与上游')
    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false)
  })

  it('不勾就保存 ⇒ 配置里搜不到那把密钥（默认口径）', () => {
    render(<SettingsPanel {...makeProps()} />)
    openTab('模型与上游')
    fillForm(SECRET)
    fireEvent.click(saveBtn())

    const blob = mem.raw[STORE_KEY] ?? ''
    expect(blob).not.toBe('')
    expect(blob).not.toContain(SECRET)
    expect(screen.getByText(/不存密钥/)).toBeTruthy()
  })

  it('勾上才存 ⇒ 记录里有那把 key，且回执明说「含密钥」', () => {
    render(<SettingsPanel {...makeProps()} />)
    openTab('模型与上游')
    fireEvent.click(screen.getByRole('checkbox'))
    fillForm(SECRET)
    fireEvent.click(saveBtn())

    expect(mem.raw[STORE_KEY] ?? '').toContain(SECRET)
    expect(screen.getByText(/含密钥/)).toBeTruthy()
  })

  it('本机 Ollama 不摆密钥输入框（本地推理用不上，占着只是噪音）', () => {
    render(<SettingsPanel {...makeProps({ upstream: { ...UPSTREAM, kind: 'ollama' } })} />)
    openTab('模型与上游')
    expect(screen.queryByPlaceholderText('API key')).toBeNull()
    expect(screen.queryByRole('checkbox')).toBeNull()
  })

  it('应用时密钥框留空且本机没存过 ⇒ patch 里干脆不带 api_key 字段', async () => {
    // 后端 `api_key=None` 才是"不动"、传 '' 是清空：把整个字段省掉才不会被洗掉。
    const onApplyUpstream = vi.fn(async (_p: unknown) => null)
    render(<SettingsPanel {...makeProps({ onApplyUpstream })} />)
    openTab('模型与上游')
    fireEvent.click(screen.getByRole('button', { name: '应用' }))

    await waitFor(() => expect(onApplyUpstream).toHaveBeenCalledTimes(1))
    const patch = onApplyUpstream.mock.calls[0][0] as Record<string, unknown>
    expect('api_key' in patch).toBe(false)
    expect(patch).toMatchObject({ kind: 'openai', model: 'deepseek-chat' })
  })

  it('填了密钥就以填的为准', async () => {
    const onApplyUpstream = vi.fn(async (_p: unknown) => null)
    render(<SettingsPanel {...makeProps({ onApplyUpstream })} />)
    openTab('模型与上游')
    fireEvent.change(screen.getByPlaceholderText('API key'), { target: { value: SECRET } })
    fireEvent.click(screen.getByRole('button', { name: '应用' }))

    await waitFor(() => expect(onApplyUpstream).toHaveBeenCalledTimes(1))
    expect(onApplyUpstream.mock.calls[0][0]).toMatchObject({ api_key: SECRET })
  })

  it('切到 Ollama 反而要显式清空密钥（空串=清掉），免得上一把留在后端内存里', async () => {
    const onApplyUpstream = vi.fn(async (_p: unknown) => null)
    render(<SettingsPanel {...makeProps({ onApplyUpstream })} />)
    openTab('模型与上游')
    fireEvent.change(kindSelect(), { target: { value: 'ollama' } })
    fireEvent.click(screen.getByRole('button', { name: '应用' }))

    await waitFor(() => expect(onApplyUpstream).toHaveBeenCalledTimes(1))
    expect(onApplyUpstream.mock.calls[0][0]).toMatchObject({ kind: 'ollama', api_key: '' })
  })

  it('换形态要把地址换成该形态的默认值，模型作废重选', () => {
    // 不然会残留上一个形态的地址：Ollama 恰好兼容 OpenAI 协议，探测与应用全都
    // 成功，用户只会觉得"配置怎么不生效"。
    render(<SettingsPanel {...makeProps()} />)
    openTab('模型与上游')
    expect(screen.getByPlaceholderText('https://api.example.com/v1')).toHaveProperty('value', UPSTREAM.base_url)

    fireEvent.change(kindSelect(), { target: { value: 'ollama' } })
    expect(screen.getByPlaceholderText('http://127.0.0.1:11434/v1')).toHaveProperty('value', 'http://127.0.0.1:11434/v1')
    expect(screen.getByPlaceholderText('模型名（可手填）')).toHaveProperty('value', '')
  })

  it('cloud 形态没填地址就点「应用」：本地拦下，不把上游指到空串', async () => {
    const onApplyUpstream = vi.fn(async (_p: unknown) => null)
    render(<SettingsPanel {...makeProps({ upstream: { ...UPSTREAM, base_url: '' } })} />)
    openTab('模型与上游')
    fireEvent.click(screen.getByRole('button', { name: '应用' }))

    expect(onApplyUpstream).not.toHaveBeenCalled()
    expect(screen.getByText('先填端点地址，再应用。')).toBeTruthy()
  })
})

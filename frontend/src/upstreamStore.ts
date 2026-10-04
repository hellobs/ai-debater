/** 已保存的上游配置 —— 存在**本机浏览器**里，支持多份、随时切换。
 *
 * 为什么需要它
 * ------------
 * 上游原本只在后端进程内存里（见后端 `app/upstream.py`）。那对开发是干净的：
 * 凭据不落盘、不回显、重启即失效。但对真实使用者很糟 —— **每次重启后端都要
 * 把地址和密钥重填一遍**，而配云端的人恰恰每次都要用它。
 *
 * 存在哪、不存哪
 * --------------
 * - **存**：浏览器 `localStorage`（本机，随浏览器 profile 走）。
 * - **不存**：仓库、`.env`、后端磁盘、任何会被提交或分享的地方。
 *   后端仍是"只收内存"的：页面加载时把保存的那份送过去，后端照旧不落盘。
 *
 * 安全边界如实说（不假装加密），以及"存不存"的默认
 * --------------------------------------------------
 * `api_key` 是**明文**存进 localStorage 的 —— base64 之类只是把明文藏起来，
 * 挡不住任何有心的人，反而让人误以为安全。所以存明文，并把这件事写进界面：
 * 本机可读、不上传第三方（只发给本机后端）、一键可清除。
 *
 * **默认不存密钥**（体检第四轮拍板）。保存一份配置时，除非显式勾了
 * 「记住密钥到本机」，否则这条记录里的 `api_key` 一律写空 —— 不是"存了但藏起来"，
 * 是根本没有。理由：明文密钥躺在浏览器里这件事，该由使用者的显式决定来触发，
 * 不该由"顺手点了保存"带来。没记住的密钥照旧能用：应用时它会被送进后端内存，
 * 只是不写进本机存储，下次打开重新填一次即可。
 *
 * **界面永不回显明文**：载入一份已保存配置时，密钥输入框保持为空，只提示
 * "已保存一把密钥"；要换就填新的覆盖，要清除就删掉这份配置。
 */
import type { UpstreamPatch } from './types'

export interface SavedUpstream {
  /** 用户起的名字，例如「我的 DeepSeek」 */
  name: string
  kind: string
  base_url: string
  model: string
  /** 明文（见文件头说明）。不需要密钥的形态（本机 Ollama）存空串。
   *  默认也是空串 —— 只有显式勾选「记住密钥」时才会被写进本机存储。 */
  api_key: string
  saved_at: number
}

/** 保存一条配置时用户给的字段。与 `SavedUpstream` 的差别只有两处：
 *  `api_key` 可以**不传**（= 别把这把密钥写进本机存储，默认），
 *  `remember_key` 记"界面上勾没勾记住密钥"。
 */
export type SaveUpstreamInput = Omit<SavedUpstream, 'saved_at' | 'api_key'> & {
  api_key?: string
  remember_key?: boolean
}

const STORE_KEY = 'debater.upstreams.v1'
/** 上次用的是哪一份（名字）。下次打开自动应用它。 */
const LAST_KEY = 'debater.upstream.last.v1'

function read(): SavedUpstream[] {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    if (!raw) return []
    const data = JSON.parse(raw)
    return Array.isArray(data) ? (data as SavedUpstream[]) : []
  } catch {
    // 存储被清、被禁用、或格式变了：一律当作"没有保存过"，不要弹错打断使用
    return []
  }
}

function write(list: SavedUpstream[]): SavedUpstream[] {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(list))
  } catch {
    /* 隐私模式下写不进去；不阻断主流程 */
  }
  return list
}

export function loadSaved(): SavedUpstream[] {
  return read()
}

export function findSaved(name: string): SavedUpstream | null {
  return read().find((c) => c.name === name) ?? null
}

/**
 * 同名覆盖。三条密钥规则，别混：
 *
 * 1. **不传 `api_key` = 不存** —— 这条记录里的密钥写空（默认行为，见文件头）。
 *    刻意不写成"沿用这份已有的那把"：那会让"取消勾选后保存"变成空操作，
 *    密钥静静躺在 localStorage 里，界面上却说"没记住"。
 * 2. **勾了 `remember_key` 却没重填** → 沿用这份已有的那把。老理由：只改个模型
 *    就把密钥洗掉，用户下一次「应用」就 401。
 * 3. **传了 `api_key`**（哪怕空串）→ 以传的为准，空串就是"这份不再带密钥"。
 */
export function saveConfig(input: SaveUpstreamInput): SavedUpstream[] {
  const list = read()
  const existing = list.find((c) => c.name === input.name)
  const incoming = (input.api_key ?? '').trim()
  const recall = input.remember_key === true ? existing?.api_key ?? '' : ''
  const merged: SavedUpstream = {
    name: input.name,
    kind: input.kind,
    base_url: input.base_url,
    model: input.model,
    api_key: incoming || recall,
    saved_at: Date.now(),
  }
  const next = existing
    ? list.map((c) => (c.name === input.name ? merged : c))
    : [...list, merged]
  setLast(input.name)
  return write(next)
}

export function removeConfig(name: string): SavedUpstream[] {
  const next = read().filter((c) => c.name !== name)
  if (getLast() === name) {
    try {
      localStorage.removeItem(LAST_KEY)
    } catch {
      /* 忽略 */
    }
  }
  return write(next)
}

/** 全部清除 —— 界面上的"清除本机保存的凭据"走的这里。 */
export function clearAll(): SavedUpstream[] {
  // 两个键都**整个删掉**，而不是写回空数组/空串：
  // 「清除全部」之后本机不该还留一个看得见的空壳（devtools 里一眼能查）。
  for (const key of [LAST_KEY, STORE_KEY]) {
    try {
      localStorage.removeItem(key)
    } catch {
      /* 隐私模式下删不掉也不该让界面报错 */
    }
  }
  return []
}

export function getLast(): string | null {
  try {
    return localStorage.getItem(LAST_KEY)
  } catch {
    return null
  }
}

/** 内部用：记下"上次用的是哪一份"，供下次打开自动应用。只被 `saveConfig` 调，
 *  不对外 —— 外部要读是 `getLast()`。 */
function setLast(name: string): void {
  try {
    localStorage.setItem(LAST_KEY, name)
  } catch {
    /* 忽略 */
  }
}

/**
 * 把一份已保存的配置变成提交给后端的字段。
 *
 * 密钥**能省则省**：`api_key: ''` 在后端是"清空"（`upstream.update` 里
 * `api_key=None` 才是"不动"），一份没记住密钥的配置照旧送去会把后端内存里
 * 那把（从 `.env` 起上来的）洗掉 —— 症状是刚应用完就"密钥未设置"。
 */
export function toPatch(saved: SavedUpstream): UpstreamPatch {
  const patch: UpstreamPatch = {
    kind: saved.kind,
    base_url: saved.base_url,
    model: saved.model,
  }
  if (saved.api_key) patch.api_key = saved.api_key
  return patch
}

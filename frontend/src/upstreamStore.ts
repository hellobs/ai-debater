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
 * 安全边界如实说（不假装加密）
 * ----------------------------
 * `api_key` 是**明文**存进 localStorage 的 —— base64 之类只是把明文藏起来，
 * 挡不住任何有心的人，反而让人误以为安全。所以存明文，并把这件事写进界面：
 * 本机可读、不上传第三方（只发给本机后端）、一键可清除。
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
  /** 明文（见文件头说明）。不需要密钥的形态（本机 Ollama）存空串。 */
  api_key: string
  saved_at: number
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

/** 同名覆盖。密钥留空时沿用这份已有的那把 —— 否则"只改个模型"会把密钥洗掉。 */
export function saveConfig(input: Omit<SavedUpstream, 'saved_at'>): SavedUpstream[] {
  const list = read()
  const existing = list.find((c) => c.name === input.name)
  const merged: SavedUpstream = {
    ...input,
    api_key: input.api_key || existing?.api_key || '',
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
  try {
    localStorage.removeItem(LAST_KEY)
  } catch {
    /* 忽略 */
  }
  return write([])
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

/** 把一份已保存的配置变成提交给后端的字段（含密钥）。 */
export function toPatch(saved: SavedUpstream): UpstreamPatch {
  return {
    kind: saved.kind,
    base_url: saved.base_url,
    model: saved.model,
    api_key: saved.api_key,
  }
}

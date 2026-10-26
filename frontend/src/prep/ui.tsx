/** 备赛模式的四个板块共用的小组件与格式化函数。 */
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

/** 一行可编辑文本（与参谋列同款交互：点开就能改） */
export function Editable(props: {
  label?: string
  value: string
  rows?: number
  onChange: (v: string) => void
}) {
  const { label, value, rows = 1, onChange } = props
  return (
    <div className="field">
      {label && <span className="field-label">{label}</span>}
      <textarea
        className="field-input"
        rows={rows}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  )
}

/** 复制文本到剪贴板，成功后短暂显示 ✓ */
export function useCopy(): [boolean, (text: string) => void] {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])
  const copy = (text: string) => {
    void navigator.clipboard?.writeText(text).then(() => {
      setCopied(true)
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => setCopied(false), 1500)
    })
  }
  return [copied, copy]
}

/** 板块容器：标题 + 可选的悬停说明 */
export function Section(props: { title: string; tip?: string; children: ReactNode }) {
  return (
    <section className="prep-card">
      <h3 className="prep-title" title={props.tip}>{props.title}</h3>
      {props.children}
    </section>
  )
}

/** 字数 → 预计朗读时长 */
export function fmtDuration(chars: number): string {
  const sec = Math.round((chars / 320) * 60)   // 辩论语速约 320 字/分钟
  return `${Math.floor(sec / 60)} 分 ${sec % 60} 秒`
}

/** 下载一段文本为 Markdown 文件（0 消耗）。标题清洗 Windows 非法文件名字符。 */
export function downloadMd(title: string, text: string): void {
  const safe = (title || '文稿').slice(0, 30).replace(/[/\\:*?"<>|]/g, '－')
  const blob = new Blob([text + '\n'], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${safe}.md`
  a.click()
  URL.revokeObjectURL(url)
}

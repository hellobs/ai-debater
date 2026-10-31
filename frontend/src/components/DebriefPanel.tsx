/** AI 复盘教练：把本会话的对方发言与台账交给模型，出一份教练视角复盘（1 次上游调用）。
 *  结果不落库——复盘是"随时可再生成"的现场服务，导出复盘仍走传统的 Markdown/Word。 */
import { useEffect, useRef, useState } from 'react'
import { sessionDebrief } from '../api'
import { isSpeaking, speak, stopSpeaking } from './speak'

export default function DebriefPanel({ sessionId }: { sessionId: string | null }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [copied, setCopied] = useState(false)
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => { if (copyTimer.current) clearTimeout(copyTimer.current) }, [])
  // 换会话清空上一场的复盘（替代曾用的 key=sessionId 卸载重挂）
  useEffect(() => {
    setText('')
    setErr('')
  }, [sessionId])

  if (!sessionId) return null

  const run = async () => {
    setBusy(true)
    setErr('')
    try {
      const data = await sessionDebrief(sessionId)
      if (data.ok && data.text) setText(data.text)
      else setErr(data.error ?? '未知错误')
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  const copyText = () => {
    void navigator.clipboard?.writeText(text).then(() => {
      setCopied(true)
      if (copyTimer.current) clearTimeout(copyTimer.current)
      copyTimer.current = setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <section className="ledger debrief">
      <header className="ledger-head">
        <h3>AI 复盘</h3>
        <span className="ledger-meta">
          {busy ? '复盘生成中…' : text ? '教练视角 · 基于本会话记录' : '对方发言 + 台账 → 打法画像 / 我方战况 / 下场建议'}
        </span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button
            className="btn-mini"
            disabled={busy}
            title="汇总对方发言与台账生成复盘；1 次上游调用，超时也计费"
            onClick={() => void run()}
          >
            {busy ? '生成中…' : text ? '重新生成（1 次调用）' : '生成复盘（1 次调用）'}
          </button>
          {text && (
            <button className="btn-mini" title="复制复盘全文" onClick={copyText}>
              {copied ? '✓ 已复制' : '复制'}
            </button>
          )}
        </span>
      </header>
      {err && <p className="error">{err}</p>}
      {text && (
        <>
          <button
            className="btn-mini"
            style={{ marginBottom: 6 }}
            title="朗读复盘全文（浏览器 TTS，0 消耗）"
            onClick={() => { if (isSpeaking()) stopSpeaking(); else speak(text) }}
          >
            {isSpeaking() ? '■ 停止朗读' : '🔊 朗读'}
          </button>
          <pre className="debrief-out">{text}</pre>
        </>
      )}
    </section>
  )
}

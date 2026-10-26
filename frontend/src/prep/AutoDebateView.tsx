/** 自动辩论（教学向）：AI 按标准流程打完整场，逐发言 SSE 推送。
 *  成本红线：整场 = 10–16 次上游调用，开始前必须明示；停止 = 当前发言完成后续不再发起。 */
import { useEffect, useRef, useState } from 'react'
import { Section, useCopy } from './ui'

interface DebateTurn {
  stage: string
  side: 'pro' | 'con'
  speaker: string
  text: string
}

/** 备赛稿导出 Word（后端 python-docx 直出，0 消耗） */
export async function downloadDraftDocx(title: string, text: string): Promise<void> {
  const res = await fetch('/api/prep/draft-docx', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'X-Debater-UI': '1' },
    body: JSON.stringify({ title, text }),
  })
  if (!res.ok) throw new Error(`docx ${res.status}`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${title || '备赛稿'}.docx`
  a.click()
  URL.revokeObjectURL(url)
}

export function AutoDebateView() {
  const [topic, setTopic] = useState('')
  const [rounds, setRounds] = useState(3)
  const [turns, setTurns] = useState<DebateTurn[]>([])
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState('')
  const [copied, copyTranscript] = useCopy()
  const abortRef = useRef<AbortController | null>(null)
  const endRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns.length])

  const total = 6 + rounds * 2 + 2
  const transcriptText = turns.map((t) => `■ ${t.speaker}（${t.stage}）\n${t.text}`).join('\n\n')
  /** 实录标题：辩题截短防路径过长；Windows 文件名非法字符换「－」，否则下载静默失败 */
  const transcriptTitle = (topic.trim() || '实录').slice(0, 30).replace(/[/\\:*?"<>|]/g, '－')
  const fileName = (ext: string) => `自动辩论·${transcriptTitle}.${ext}`
  const downloadMd = () => {
    const head = `# 自动辩论实录：${topic.trim()}\n\n`
    const blob = new Blob([head + transcriptText + '\n'], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = fileName('md')
    a.click()
    URL.revokeObjectURL(url)
  }
  const downloadDocx = async () => {
    try {
      await downloadDraftDocx(`自动辩论·${transcriptTitle}`, transcriptText)
    } catch (e) {
      setErr(`Word 导出失败：${String(e)}`)
    }
  }

  const start = () => {
    if (running || !topic.trim()) return
    setTurns([]); setErr(''); setRunning(true)
    const ctrl = new AbortController()
    abortRef.current = ctrl
    void (async () => {
      try {
        const res = await fetch('/api/prep/debate', {
          method: 'POST',
          headers: { 'content-type': 'application/json', 'X-Debater-UI': '1' },
          body: JSON.stringify({ topic, rounds }),
          signal: ctrl.signal,
        })
        if (!res.ok || !res.body) { setErr(`debate ${res.status}`); setRunning(false); return }
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          let sep: number
          while ((sep = buf.indexOf('\n\n')) >= 0) {
            const block = buf.slice(0, sep)
            buf = buf.slice(sep + 2)
            let event = 'message'
            const dataLines: string[] = []
            for (const line of block.split('\n')) {
              if (line.startsWith('event:')) event = line.slice(6).trim()
              else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
            }
            if (!dataLines.length) continue
            const data = JSON.parse(dataLines.join('\n'))
            if (event === 'turn') {
              setTurns((prev) => [...prev, data.turn as DebateTurn])
            } else if (event === 'error') {
              setErr(data.error ?? '未知错误')
              ctrl.abort(); setRunning(false); return
            } else if (event === 'done') {
              setRunning(false); return
            }
          }
        }
        setRunning(false)
      } catch (e) {
        if ((e as Error)?.name !== 'AbortError') setErr(String(e))
        setRunning(false)
      }
    })()
  }

  const stop = () => {
    // 停止 = 断开：进行中的这一次发言仍会完成并计费（上游调用无法撤回），
    // 后续发言不再发起——界面如实告知，不装作"立即免费停止"。
    abortRef.current?.abort()
    setRunning(false)
  }

  return (
    <div>
      <Section title="自动辩论" tip="AI 按标准流程（立论→驳论→质询→自由辩论→结辩）代表双方打完整场——观察打法用。不做胜负判定，不是互搏评估">
        <input
          className="text-input"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="输入完整辩题，例：AI 生成内容应不应该强制标注"
        />
        <div className="prep-grid">
          <label>自由辩论轮数
            <select className="text-input" value={rounds} onChange={(e) => setRounds(Number(e.target.value))} disabled={running}>
              {[2, 3, 4, 5].map((n) => <option key={n} value={n}>{n} 轮（整场约 {6 + n * 2 + 2} 次发言）</option>)}
            </select>
          </label>
        </div>
        <div className="prep-actions">
          {running ? (
            <button className="btn-mini" onClick={stop} title="进行中的这一次发言仍会完成并计费，后续发言不再发起">■ 停止</button>
          ) : (
            <button className="btn-mini" onClick={start} disabled={!topic.trim()}>
              开始自动辩论
            </button>
          )}
          <button className="btn-mini" onClick={() => { setTurns([]); setErr('') }} disabled={running}>清空</button>
          {turns.length > 0 && (
            <>
              <button className="btn-mini" onClick={() => copyTranscript(transcriptText)} title="复制整场实录">
                {copied ? '✓ 已复制' : '复制全文'}
              </button>
              <button className="btn-mini" onClick={downloadMd} title="下载 Markdown 实录（0 消耗）">
                下载 .md
              </button>
              <button className="btn-mini" onClick={() => void downloadDocx()} title="下载 Word 实录（后端直出，0 消耗）">
                下载 .docx
              </button>
            </>
          )}
        </div>
        <p className="hint" style={{ color: 'var(--warn)' }}>
          成本：整场 {total} 条发言 = {total} 次上游调用（轮数越多越多）。停止后，进行中的那次仍会计费。
        </p>
        {err && <p className="error">{err}</p>}
      </Section>

      {turns.map((t, i) => (
        <div key={i} className={`prep-turn ${t.side}`} title={`${t.speaker} · ${t.stage}`}>
          <div className="prep-turn-head">
            <span className="prep-turn-no">{i + 1}</span>
            <b>{t.speaker}</b>
            <span className="muted">{t.stage}</span>
          </div>
          <p className="prep-turn-text">{t.text}</p>
        </div>
      ))}
      {running && <p className="muted" style={{ textAlign: 'center' }}>AI 正在准备下一发言…</p>}
      <div ref={endRef} />
    </div>
  )
}

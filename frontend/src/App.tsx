import { useRef, useState } from 'react'
import AdvisorColumn from './components/AdvisorColumn'
import SettingsPanel from './components/SettingsPanel'
import { streamAnalyze } from './api'
import type { AdvisorResult } from './types'

/** 前端展示的参谋列（顺序与后端 advisors.yaml 一致） */
const COLUMNS = [
  { name: 'rebutter', label: '反驳手' },
  { name: 'questioner', label: '质询手' },
  { name: 'auditor', label: '逻辑审计员' },
]

const SAMPLE_TOPIC = 'AI 生成内容是否应享有著作权'
const SAMPLE_OPPONENT =
  '著作权法只保护自然人的智力成果，AI 不是人，所以 AI 生成内容不应享有著作权。'

export default function App() {
  const [topic, setTopic] = useState(SAMPLE_TOPIC)
  const [ourSide, setOurSide] = useState('控方（主张应享有）')
  const [opponentText, setOpponentText] = useState(SAMPLE_OPPONENT)

  const [results, setResults] = useState<Record<string, AdvisorResult>>({})
  const [running, setRunning] = useState(false)
  const [totalLatency, setTotalLatency] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const cancelRef = useRef<(() => void) | null>(null)

  const handleSubmit = () => {
    if (running) return
    setResults({})
    setNotice(null)
    setTotalLatency(null)
    setRunning(true)

    cancelRef.current = streamAnalyze(
      { topic, our_side: ourSide, opponent_text: opponentText },
      (r) => setResults((prev) => ({ ...prev, [r.advisor]: r })),
      (secs) => {
        setRunning(false)
        setTotalLatency(secs)
      },
      (msg) => {
        setRunning(false)
        setNotice(msg)
      },
    )
  }

  const handleReset = () => {
    cancelRef.current?.()
    cancelRef.current = null
    setResults({})
    setNotice(null)
    setTotalLatency(null)
    setRunning(false)
  }

  const okCount = Object.values(results).filter((r) => r.status === 'ok').length

  return (
    <div className="app">
      <SettingsPanel
        topic={topic}
        ourSide={ourSide}
        opponentText={opponentText}
        running={running}
        onTopic={setTopic}
        onSide={setOurSide}
        onOpponent={setOpponentText}
        onSubmit={handleSubmit}
        onReset={handleReset}
      />

      <main className="board">
        <div className="board-bar">
          <span className="board-title">参谋建议</span>
          <span className="board-meta">
            {running
              ? `已返回 ${okCount} / ${COLUMNS.length} 路…`
              : totalLatency !== null
                ? `${COLUMNS.length} 路并行 · 总耗时 ${totalLatency}s`
                : '等待提交'}
          </span>
        </div>

        {notice && <div className="notice">{notice}</div>}

        <div className="columns">
          {COLUMNS.map((c) => (
            <AdvisorColumn
              key={c.name}
              label={c.label}
              result={results[c.name]}
              running={running}
            />
          ))}
        </div>

        <p className="footnote">
          建议内容可直接点击修改。生成结果仅作参谋，最终判断与取舍在你。
        </p>
      </main>
    </div>
  )
}

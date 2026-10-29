/** 赛场计时器：比赛各环节有时限，现场辩手不该用手机计时。
 *  环节预设时长（对齐标准赛制，可微调）→ 倒计时 → 最后 30 秒警示色，归零停表。
 *  纯前端，0 消耗。 */
import { useEffect, useRef, useState } from 'react'

/** 标准赛制各环节的常规时限（秒）。自由辩论按各方 4 分钟。 */
const PRESETS: [string, number][] = [
  ['立论陈词', 180],
  ['驳论反驳', 120],
  ['质询', 90],
  ['质询小结', 90],
  ['半场小结', 120],
  ['自由辩论', 240],
  ['结辩陈词', 180],
]

function fmt(sec: number): string {
  const s = Math.max(0, Math.ceil(sec))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export default function MatchTimer() {
  const [preset, setPreset] = useState(PRESETS[0])
  const [total, setTotal] = useState(PRESETS[0][1])
  const [left, setLeft] = useState(PRESETS[0][1])
  const [running, setRunning] = useState(false)
  const [finished, setFinished] = useState(false)
  const tick = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => () => { if (tick.current) clearInterval(tick.current) }, [])

  useEffect(() => {
    if (!running) return
    tick.current = setInterval(() => {
      setLeft((v) => {
        if (v <= 0.1) {
          setRunning(false)
          setFinished(true)
          return 0
        }
        return v - 0.25
      })
    }, 250)
    return () => { if (tick.current) clearInterval(tick.current) }
  }, [running])

  const pick = (p: [string, number]) => {
    setPreset(p)
    setTotal(p[1])
    setLeft(p[1])
    setRunning(false)
    setFinished(false)
  }
  const reset = () => {
    setLeft(total)
    setRunning(false)
    setFinished(false)
  }

  const warn = running && left <= 30 && left > 0
  const danger = left <= 0 || (running && left <= 10)
  const color = finished || danger ? 'var(--warn)' : warn ? 'var(--amber)' : 'var(--accent)'

  return (
    <div className="match-timer">
      <select
        className="text-input"
        style={{ width: 'auto' }}
        value={preset[0]}
        disabled={running}
        onChange={(e) => pick(PRESETS.find((p) => p[0] === e.target.value) ?? PRESETS[0])}
      >
        {PRESETS.map(([name]) => <option key={name} value={name}>{name}</option>)}
      </select>
      <span
        className={`match-timer-digits${finished ? ' match-timer-done' : ''}`}
        style={{ color }}
        title={finished ? '时间到' : warn ? '最后 30 秒' : undefined}
      >
        {fmt(left)}
      </span>
      <button
        className="btn-mini"
        onClick={() => { if (left > 0) setRunning((v) => !v) }}
        disabled={finished}
      >
        {running ? '暂停' : left < total && left > 0 ? '继续' : '开始'}
      </button>
      <button className="btn-mini" onClick={reset}>复位</button>
      {finished && <span style={{ color: 'var(--warn)', fontSize: 12 }}>时间到</span>}
    </div>
  )
}

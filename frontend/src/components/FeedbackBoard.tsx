/** 参谋反馈看板（服务状态页 ⑧）：按参谋聚合本机全部反馈——评分均值、
 *  收录样本数、最近评语。数据是反馈闭环的**结果侧**：哪一路分低，下一轮
 *  提示词迭代就有依据。纯本地读取，0 消耗。 */
import { useCallback, useEffect, useState } from 'react'
import { fetchFeedback, type FeedbackRow } from '../api'

interface AdvisorStat {
  advisor: string
  count: number
  avg: number | null
  selected: number
  lastNote: string
  lastAt: string
}

function aggregate(rows: FeedbackRow[]): AdvisorStat[] {
  const by = new Map<string, FeedbackRow[]>()
  for (const r of rows) {
    const list = by.get(r.advisor) ?? []
    list.push(r)
    by.set(r.advisor, list)
  }
  return [...by.entries()]
    .map(([advisor, list]) => {
      const rated = list.filter((r) => typeof r.rating === 'number')
      const last = list[list.length - 1]
      return {
        advisor,
        count: list.length,
        avg: rated.length
          ? rated.reduce((a, r) => a + (r.rating ?? 0), 0) / rated.length
          : null,
        selected: list.filter((r) => r.selected).length,
        lastNote: last?.note ?? '',
        lastAt: last?.created_at ?? '',
      }
    })
    .sort((a, b) => (a.avg ?? 9) - (b.avg ?? 9))   // 分低的排前面——它们才是待改进项
}

export default function FeedbackBoard() {
  const [stats, setStats] = useState<AdvisorStat[] | null>(null)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    setErr('')
    try {
      setStats(aggregate(await fetchFeedback()))
    } catch (e) {
      setErr(String(e))
    }
  }, [])

  useEffect(() => { void load() }, [load])

  return (
    <div className="session-block">
      <span className="block-label">⑧ 参谋反馈看板</span>
      <div className="model-row">
        <span className="muted">
          {stats && stats.length
            ? `${stats.length} 路有反馈（低分在前）——哪路弱，提示词就先改哪路`
            : '还没有反馈 —— 给参谋卡评分后这里会出现'}
        </span>
        <button className="btn-mini" onClick={() => void load()}>刷新</button>
      </div>
      {err && <p className="warn-block" style={{ marginTop: 6 }}>{err}</p>}
      {stats && stats.length > 0 && (
        <ul className="session-items">
          {stats.map((s) => (
            <li key={s.advisor} title={s.lastNote ? `最近评语：${s.lastNote}` : undefined}>
              <span className="session-topic">{s.advisor}</span>
              <span className="muted">
                {s.avg !== null ? `均分 ${s.avg.toFixed(1)} · ` : '未评分 · '}
                {s.count} 条{s.selected ? ` · 收录样本 ${s.selected}` : ''}
              </span>
              {s.avg !== null && s.avg < 3 && <em className="ledger-warn">待改进</em>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

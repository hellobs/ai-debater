import type { MetricsInfo } from '../types'

const fmt = (v: number | null, unit = 's') => (v === null ? '—' : `${v}${unit}`)

export default function MetricsPanel(props: {
  metrics: MetricsInfo | null
  labels: Record<string, string>
}) {
  const { metrics, labels } = props
  const names = metrics ? Object.keys(metrics.advisors) : []

  return (
    <section className="metrics">
      <header className="metrics-head">
        <h3>现场仪表</h3>
        <span className="metrics-meta">
          {metrics
            ? `默认预算 ${metrics.budget_s}s · 数据来自历史全部对局`
            : '暂无数据'}
        </span>
      </header>

      {!metrics || names.length === 0 ? (
        <p className="muted">跑过一次分析后，这里会显示各路参谋的延迟分布。</p>
      ) : (
        <table className="metrics-table">
          <thead>
            <tr>
              <th>参谋</th>
              <th>样本</th>
              <th>成功</th>
              <th>超时</th>
              <th>失败</th>
              <th>P50</th>
              <th>P95</th>
              <th>最慢</th>
            </tr>
          </thead>
          <tbody>
            {names.map((n) => {
              const m = metrics.advisors[n]
              return (
                <tr key={n}>
                  <td>{labels[n] ?? n}</td>
                  <td>{m.total}</td>
                  <td>{m.ok}</td>
                  <td className={m.timeout > 0 ? 'warn-cell' : ''}>{m.timeout}</td>
                  <td className={m.error > 0 ? 'warn-cell' : ''}>{m.error}</td>
                  <td>{fmt(m.p50)}</td>
                  <td>{fmt(m.p95)}</td>
                  <td>{fmt(m.max)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </section>
  )
}

import type { HealthInfo, MetricsInfo } from '../types'

const fmt = (v: number | null, unit = 's') => (v === null ? '—' : `${v}${unit}`)

/** mavis 的计数器格式：`S:成功,F:最终失败/R:完成的请求数` */
const SUMMARY_RE = /S:(\d+),\s*F:(\d+)\/R:(\d+)/

function parseSummary(raw: string) {
  const m = SUMMARY_RE.exec(raw)
  if (!m) return null
  return { ok: Number(m[1]), fail: Number(m[2]), requests: Number(m[3]) }
}

const R_TITLE =
  '上游完成的请求数（mavis 的 R）。注意：抛异常的尝试不计入，' +
  '重试耗尽时 R 会是 0 —— 所以 R 不能当"尝试总数"用。'

function CallerStat(props: { label: string; raw: string }) {
  const s = parseSummary(props.raw)
  return (
    <li className="caller-stat">
      <span className="caller-name">{props.label}</span>
      <span className="caller-num">{s ? s.ok : '—'}</span>
      <span className={`caller-num${s && s.fail > 0 ? ' bad' : ''}`}>
        {s ? s.fail : '—'}
      </span>
      <span className="caller-num" title={R_TITLE}>
        {s ? s.requests : '—'}
      </span>
    </li>
  )
}

/**
 * mavis 接入状态。
 *
 * provider 那几行不是前端算的，是后端直接把 mavis `get_summary()` 的原样数据
 * 转出来的 —— 前端只做解析与着色，不再复算一遍（复算就会和真值漂移）。
 */
function ProviderStrip(props: { health: HealthInfo | null; labels: Record<string, string> }) {
  const { health, labels } = props
  const provider = health?.provider
  if (!health) {
    return (
      <div className="provider-strip off">
        <span className="dot" />
        <span>后端未连通，读不到 mavis 接入状态。</span>
      </div>
    )
  }
  if (!provider?.ready) {
    return (
      <div className="provider-strip off">
        <span className="dot" />
        <span>mavis provider 未就绪{provider?.error ? `：${provider.error}` : '。'}</span>
      </div>
    )
  }

  const callers = provider.summary?.summary ?? {}
  // 参谋顺序跟名册走；mavis 自己维护的 `total` 单独放最后
  const ordered = [
    ...Object.keys(labels).filter((n) => n in callers),
    ...Object.keys(callers).filter((n) => n !== 'total' && !(n in labels)),
  ]
  const total = callers.total
  const observers = health.observers
  const lastRun = observers?.last_run
  const mavis = health.mavis

  return (
    <div className="provider-strip">
      <div className="provider-head">
        <span className={`dot${provider.is_available ? ' on' : ' off'}`} />
        <span className="provider-title">
          {mavis ? `${mavis.framework} v${mavis.version}` : 'mavis'}
          <span className="muted"> · provider</span>
        </span>
        <span className="muted">
          {provider.summary?.model ?? health.model} ·{' '}
          {provider.is_available ? '可用' : '不可用'} · 桥 {health.bridge}
        </span>
        {total && (
          <span className="muted provider-total" title="mavis 自己维护的总计">
            总计 {total}
          </span>
        )}
      </div>

      {mavis && (
        <ul className="mavis-surfaces" title="本项目用到 mavis 的全部范围">
          {mavis.surfaces.map((s) => (
            <li key={s.key} title={`${s.entry} → ${s.used_in}\n${s.detail}`}>
              <b>{s.name}</b>
              <span className="muted"> {s.detail}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="provider-callers">
        <div className="caller-head">
          <span className="caller-name">逐参谋调用</span>
          <span className="caller-num" title="最终成功次数（mavis 的 S）">成功</span>
          <span className="caller-num" title="最终失败次数（mavis 的 F）">失败</span>
          <span className="caller-num" title={R_TITLE}>请求</span>
        </div>
        <ul>
          {ordered.length === 0 ? (
            <li className="muted">还没有调用记录 —— 跑一次分析就会出现在这里。</li>
          ) : (
            ordered.map((name) => (
              <CallerStat key={name} label={labels[name] ?? name} raw={callers[name]} />
            ))
          )}
        </ul>
      </div>

      <div className="provider-foot muted">
        本进程 {observers?.runs ?? 0} 轮
        {lastRun && (
          <>
            {' · '}最近一轮{' '}
            {Object.entries(lastRun.counts)
              .map(([k, v]) => `${k} ${v}`)
              .join(' / ') || '无结果'}
            {lastRun.total_latency_s !== null && ` · ${lastRun.total_latency_s}s`}
          </>
        )}
        {provider.cache && provider.cache.hits + provider.cache.misses === 0 && (
          <> · 结果缓存未启用（mavis 的缓存白名单只认它自己的调用名）</>
        )}
      </div>

      {mavis && (
        <div className="provider-foot muted">
          唯一接触面 <code>{mavis.contact}</code>
          {' · '}提示词模板 {mavis.prompts.templates} 个
          {mavis.observers?.length ? ` · 事件总线挂 ${mavis.observers.join(' / ')}` : ''}
          {' · '}
          {mavis.readonly ? 'mavis 只读依赖，一行未改' : 'mavis 已被改动（不再是只读依赖）'}
        </div>
      )}
    </div>
  )
}

export default function MetricsPanel(props: {
  metrics: MetricsInfo | null
  labels: Record<string, string>
  health: HealthInfo | null
}) {
  const { metrics, labels, health } = props
  const names = metrics ? Object.keys(metrics.advisors) : []

  return (
    <section className="metrics">
      <header className="metrics-head">
        <h3>现场仪表</h3>
        <span className="metrics-meta">
          {metrics
            ? `服务端默认预算 ${metrics.budget_s}s（界面选择会覆盖）· 数据来自历史全部对局`
            : '暂无数据'}
        </span>
      </header>

      <ProviderStrip health={health} labels={labels} />

      {!metrics || names.length === 0 ? (
        <p className="muted">跑过一次分析后，这里会显示各路参谋的延迟分布。</p>
      ) : (
        <table className="metrics-table">
          <thead>
            <tr>
              <th>参谋</th>
              <th>样本</th>
              <th>成功</th>
              <th>空</th>
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
                  {/* 「空」= 模型答了但内容为空；「失败」= 上游调用挂了。
                      不分开显示的话 样本 ≠ 成功+超时+失败，表格自己都对不上。 */}
                  <td title="模型应答正常但内容为空">{m.empty}</td>
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

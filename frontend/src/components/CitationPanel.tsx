import { useEffect, useState } from 'react'
import { fetchRetrievalStatus, verifyCitations } from '../api'
import { CITATION_LABEL, type CitationReport, type RetrievalStatus } from '../types'

export default function CitationPanel(props: { sessionId: string | null }) {
  const { sessionId } = props
  const [report, setReport] = useState<CitationReport | null>(null)
  const [status, setStatus] = useState<RetrievalStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const loadStatus = async (reload = false) => {
    try {
      setStatus(await fetchRetrievalStatus(reload))
    } catch {
      /* 忽略 */
    }
  }

  useEffect(() => {
    void loadStatus()
  }, [])

  const run = async () => {
    if (!sessionId || busy) return
    setBusy(true)
    setErr(null)
    try {
      setReport(await verifyCitations(sessionId))
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  const corpusHint = () => {
    if (!status) return '读取中…'
    if (!status.available) {
      return `未配置语料（${status.corpus_dir ?? 'data/corpus'}）——所有引用只能判「未核验」`
    }
    return `语料：${status.laws ?? 0} 部法律 / ${status.articles ?? 0} 条 / ${status.documents ?? 0} 份文本`
  }

  return (
    <section className="citations">
      <header className="section-head">
        <h3>引用核验</h3>
        <span className="section-meta">
          纯本地核对，不消耗 API 额度 · 存在性 + 内容一致性
        </span>
      </header>

      <div className="cite-bar">
        <button className="btn-export" onClick={() => void loadStatus(true)}>
          重载语料
        </button>
        <button
          className="btn-export"
          disabled={!sessionId || busy}
          onClick={() => void run()}
        >
          {busy ? '核对中…' : '核验本轮引用'}
        </button>
        <span className="muted">{corpusHint()}</span>
      </div>

      {err && <p className="error">{err}</p>}

      {report && (
        <>
          <p className="cite-summary">
            共 <b>{report.total}</b> 条引用：
            <span className="cite-chip verified">已核验 {report.verified}</span>
            <span className="cite-chip dubious">存疑 {report.dubious}</span>
            <span className="cite-chip unverified">未核验 {report.unverified}</span>
            {report.content_suspect > 0 && (
              <span
                className="cite-chip content-suspect"
                title="这些条款在语料里确实存在，但模型给它配的内容与原文对不上——可能是编造，也可能是意译。"
              >
                引述待查 {report.content_suspect}
              </span>
            )}
          </p>

          {report.total === 0 ? (
            <p className="muted">本轮建议里没有出现《…》第…条 形式的引用。</p>
          ) : (
            <ul className="cite-list">
              {report.items.map((c, i) => (
                <li
                  key={i}
                  className={`cite-item ${c.status}${c.content_ok === false ? ' content-suspect' : ''}`}
                >
                  <div className="cite-head">
                    <span className={`cite-chip ${c.status}`}>
                      {CITATION_LABEL[c.status]}
                    </span>
                    <code>{c.raw}</code>
                    {c.match !== null && (
                      <span
                        className={`cite-match${c.content_ok === false ? ' low' : ''}`}
                        title={
                          `模型引述的内容有多大比例能在语料原文里连续找到` +
                          `（阈值 ${Math.round(report.match_low * 100)}%）。` +
                          `低于阈值不代表一定错——意译概括也会低。`
                        }
                      >
                        重合 {Math.round(c.match * 100)}%
                      </span>
                    )}
                  </div>
                  {c.claimed && (
                    <p className="cite-claimed">
                      <span className="cite-label">模型引述</span>
                      {c.claimed}
                    </p>
                  )}
                  {c.evidence && (
                    <p className="cite-evidence">
                      <span className="cite-label">语料原文</span>
                      {c.evidence}
                    </p>
                  )}
                  {c.note && <p className="cite-note">{c.note}</p>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {!report && !sessionId && (
        <p className="muted">先跑一轮分析，再来核验引用。</p>
      )}
    </section>
  )
}

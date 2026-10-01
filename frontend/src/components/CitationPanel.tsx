import { useEffect, useRef, useState } from 'react'
import { fetchRetrievalStatus, importCorpus, verifyCitations } from '../api'
import { CITATION_LABEL, type CitationReport, type RetrievalStatus } from '../types'

export default function CitationPanel(props: {
  sessionId: string | null
  /** 分析完成时由 App 自动核验所得的报告（UX-2）。变化即落入本面板展示。 */
  autoReport?: CitationReport | null
}) {
  const { sessionId, autoReport } = props
  const [report, setReport] = useState<CitationReport | null>(null)
  const [status, setStatus] = useState<RetrievalStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  // ---- 语料导入（阶段 4 补充）：队友现场不会开终端，导入搬进界面 ----
  const [impOpen, setImpOpen] = useState(false)
  const [impLaw, setImpLaw] = useState('')
  const [impText, setImpText] = useState('')
  const [impMsg, setImpMsg] = useState('')
  const [impBusy, setImpBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

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

  // UX-2：分析完成时 App 会自动核验一次，报告经此落入面板——
  // 用户不用再发现「下面还有个手动按钮」。手动核验仍可重跑覆盖。
  useEffect(() => {
    if (autoReport) setReport(autoReport)
  }, [autoReport])

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

  /** 把选中的文本文件读进粘贴框——之后走同一条导入路径，人还能看一眼再导。 */
  const readFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    void f.text().then((t) => {
      setImpText(t)
      if (!impLaw.trim()) {
        // 文件名兜底只作占位提示，真正的法名仍以正文标题/输入框为准
        setImpLaw(impLaw || f.name.replace(/\.(txt|md)$/i, ''))
      }
      e.target.value = ''
    })
  }

  const doImport = async () => {
    if (impBusy || !impText.trim()) return
    setImpBusy(true)
    setImpMsg('')
    try {
      const data = await importCorpus(impLaw.trim(), impText)
      if (data.error || !data.ok) {
        setImpMsg(`导入失败：${data.error ?? '未知原因'}`)
      } else {
        const warn = data.warnings?.length ? `（提示：${data.warnings.join('；')}）` : ''
        setImpMsg(
          `已导入《${data.law}》${data.articles} 条；语料库现有 ${data.total_laws} 部 / ${data.total_articles} 条${warn}`,
        )
        setImpText('')
        setImpLaw('')
        await loadStatus(true)
      }
    } catch (e) {
      setImpMsg(`导入请求失败：${String(e)}`)
    } finally {
      setImpBusy(false)
    }
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
        <button
          className="btn-export"
          onClick={() => setImpOpen((v) => !v)}
          title="把法条全文（txt/md）导入语料库，让「已核验」判定可用"
        >
          {impOpen ? '收起导入' : '导入语料'}
        </button>
        <span className="muted">{corpusHint()}</span>
      </div>

      {impOpen && (
        <div className="corpus-import">
          <div className="model-row">
            <input
              className="text-input"
              value={impLaw}
              onChange={(e) => setImpLaw(e.target.value)}
              placeholder="法名（留空则从正文首行《XX法》识别）"
            />
            <button className="btn-mini" onClick={() => fileRef.current?.click()}>
              选文件
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".txt,.md,text/plain"
              style={{ display: 'none' }}
              onChange={readFile}
            />
          </div>
          <textarea
            className="text-input"
            rows={6}
            value={impText}
            onChange={(e) => setImpText(e.target.value)}
            placeholder="粘贴法条全文（要求行首有「第X条」，每条一段）。来源请用官方文本（flk.npc.gov.cn），不要凭记忆录入——那会把错误固化成「已核验」。"
          />
          <div className="row-actions">
            <button
              className="btn-mini"
              disabled={impBusy || !impText.trim()}
              onClick={() => void doImport()}
            >
              {impBusy ? '导入中…' : '导入'}
            </button>
            <span className="hint">同名法整体替换；导入后引用核验立即生效，不必重启。</span>
          </div>
          {impMsg && <p className="hint">{impMsg}</p>}
        </div>
      )}

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

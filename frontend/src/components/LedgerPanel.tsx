import type { CardStatus, Conflict, LedgerCard } from '../types'
import { STATUS_LABEL } from '../types'

const STATUSES: CardStatus[] = ['standing', 'weakened', 'abandoned']

export default function LedgerPanel(props: {
  cards: LedgerCard[]
  conflicts: Conflict[]
  busy: boolean
  onStatus: (cardId: string, status: CardStatus) => void
  onDelete: (cardId: string) => void
}) {
  const { cards, conflicts, busy, onStatus, onDelete } = props
  const conflictedIds = new Set(conflicts.map((c) => c.card_id).filter(Boolean))

  return (
    <section className="ledger">
      <header className="ledger-head">
        <h3>我方论点台账</h3>
        <span className="ledger-meta">
          {cards.length ? `${cards.length} 条主张` : '还没有采纳任何主张'}
          {conflicts.length > 0 && (
            <em className="ledger-warn"> · {conflicts.length} 处立场冲突</em>
          )}
        </span>
      </header>

      {conflicts.length > 0 && (
        <ul className="conflict-list">
          {conflicts.map((c, i) => (
            <li key={i}>
              <b>冲突</b> 新建议「{c.new_claim}」与你此前主张的
              「{c.card_claim}」不能同时为真 —— {c.reason}
            </li>
          ))}
        </ul>
      )}

      {cards.length === 0 ? (
        <p className="muted">
          在反驳手给出的论点卡片上点「采纳为我方主张」，它就会进台账；
          之后每次分析都会自动带上，避免参谋给出与己方立场冲突的建议。
        </p>
      ) : (
        <div className="ledger-grid">
          {cards.map((c) => (
            <article
              className={`ledger-card${conflictedIds.has(c.id) ? ' conflicted' : ''}`}
              key={c.id}
            >
              <div className="ledger-card-head">
                <span className="badge badge-point">{c.id}</span>
                <select
                  className="status-select"
                  value={c.status}
                  disabled={busy}
                  onChange={(e) => onStatus(c.id, e.target.value as CardStatus)}
                >
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>{STATUS_LABEL[s]}</option>
                  ))}
                </select>
              </div>
              <p className="ledger-claim">{c.claim}</p>
              {c.major_premise && (
                <p className="ledger-basis">依据：{c.major_premise}</p>
              )}
              <div className="ledger-card-foot">
                <span className="muted">{c.source}</span>
                <button
                  className="btn-mini danger"
                  disabled={busy}
                  onClick={() => onDelete(c.id)}
                >
                  删除
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

import { useMemo, useState } from 'react'
import type { DocSummary } from '../types'
import { HISTORY_LIMIT } from '../hooks'
import { api } from '../api'
import { ms, usd } from '../ReviewUI'
import { IconClose, IconDoc, IconSearch } from './Icons'
import { Segmented } from './Toolbar'

/* Home is the record of everything ever processed - the old History tab, which
   is what people actually open the app to look at. Uploading is the thing you
   do occasionally; reviewing what came back is the thing you do daily, so it
   gets the front door. */

type Sort = 'recent' | 'review' | 'slowest'

/* File names are written every which way - invoice_026.pdf, invoice-026,
   "Invoice 026". Collapsing separators on both sides means any of those spellings
   finds the file, which is the difference between a search that works and one
   you have to guess the punctuation for. */
const norm = (v: string) => v.toLowerCase().replace(/[\s._\-/\\]+/g, '')

const SORTS: { id: Sort; label: string }[] = [
  { id: 'recent',  label: 'Newest' },
  { id: 'review',  label: 'Needs review' },
  { id: 'slowest', label: 'Slowest' },
]

export function HomeStats({ docs }: { docs: DocSummary[] }) {
  /* A document whose provider reported no price has cost_usd === null, which is
     NOT zero. Those are counted separately so the total reads as a floor with a
     stated gap, rather than a confident number quietly omitting paid calls. */
  const priced = docs.filter(d => d.cost_usd !== null && d.cost_usd !== undefined)
  const unpriced = docs.length - priced.length
  const totalUsd = priced.reduce((s, d) => s + (d.cost_usd as number), 0)
  const allFree = priced.length > 0 && priced.every(d => d.cost_usd === 0)
  const timed = docs.filter(d => d.total_ms)
  const totalMs = timed.reduce((s, d) => s + (d.total_ms as number), 0)
  const avgAccept = docs.length
    ? docs.reduce((s, d) => s + d.auto_accept_rate, 0) / docs.length
    : 0

  return (
    <>
      <div className="summary">
        <div className="stat">
          <div className="k">{docs.length >= HISTORY_LIMIT ? `Documents (last ${HISTORY_LIMIT})` : 'Documents'}</div>
          <div className="v">{docs.length}</div>
        </div>
        <div className="stat">
          <div className="k">Mean auto-accept</div>
          <div className={`v ${avgAccept >= 0.85 ? 'green' : 'amber'}`}>
            {Math.round(avgAccept * 100)}%
          </div>
        </div>
        {timed.length > 0 && (
          <div className="stat">
            <div className="k">{timed.length < docs.length ? `Total time (${timed.length} timed)` : 'Total time'}</div>
            <div className="v" style={{ fontSize: 19 }}>{ms(totalMs)}</div>
          </div>
        )}
        {priced.length > 0 && (
          <div className="stat">
            <div className="k">{unpriced > 0 ? `Total cost (${unpriced} unpriced)` : 'Total cost'}</div>
            <div className={`v ${unpriced > 0 ? 'amber' : ''}`} style={{ fontSize: 19 }}>
              {allFree && unpriced === 0 ? 'free tier' : usd(totalUsd)}
            </div>
          </div>
        )}
      </div>

      {(unpriced > 0 || timed.length < docs.length) && (
        <p className="timing-note" style={{ marginTop: -8, marginBottom: 16 }}>
          {unpriced > 0 && `${unpriced} document(s) have no recorded price — either the provider reported none, or they were processed before cost tracking existed. The total above is a floor, not the full spend. `}
          {timed.length < docs.length && `${docs.length - timed.length} document(s) predate timing and are excluded from the total time.`}
        </p>
      )}
    </>
  )
}

export default function Home({ docs, activeId, onOpen, onDelete, deletingId }: {
  docs: DocSummary[]
  activeId: string | null
  onOpen: (d: DocSummary) => void
  onDelete: (id: string) => void
  deletingId: string | null
}) {
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<Sort>('recent')
  const [confirmId, setConfirmId] = useState<string | null>(null)
  // Off by default: exporting everything (including fields still waiting on a
  // human) is the honest default, since silently dropping rows out of an
  // export is more surprising than including a review_status column that
  // flags them.
  const [cleanOnly, setCleanOnly] = useState(false)

  /* File name only, and the control says so on its face.

     The previous version also matched the provider and looked identical to the
     in-invoice field search, so typing "gstin" here returned nothing and read as
     broken - it was searching file names all along. Narrowing the scope does not
     fix that on its own; naming the scope does. Hence the "File name" label on
     the box and an empty state that says where to search field values instead. */
  const shown = useMemo(() => {
    const needle = norm(q)
    const copy = needle
      ? docs.filter(d => norm(d.filename).includes(needle))
      : [...docs]
    if (sort === 'review') {
      // Lowest auto-accept first: the ones with the most left for a human.
      copy.sort((a, b) => a.auto_accept_rate - b.auto_accept_rate)
    } else if (sort === 'slowest') {
      copy.sort((a, b) => (b.total_ms ?? 0) - (a.total_ms ?? 0))
    } else {
      copy.sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at))
    }
    return copy
  }, [docs, q, sort])

  return (
    <>
      <HomeStats docs={docs} />

      <div className="listtools">
        <div className="listsearch">
          <span className="scope"><IconSearch size={13} /> File name</span>
          <input
            type="text"
            value={q}
            placeholder="e.g. invoice_026"
            aria-label="Find an invoice by file name"
            onChange={e => setQ(e.target.value)}
            onKeyDown={e => { if (e.key === 'Escape' && q) { e.preventDefault(); setQ('') } }}
          />
          {q && (
            <button className="clear" onClick={() => setQ('')} aria-label="Clear">
              <IconClose size={12} />
            </button>
          )}
        </div>
        <Segmented value={sort} options={SORTS} onChange={setSort} label="Sort documents" />
      </div>

      {docs.length > 0 && (
        <div className="listtools" style={{ marginTop: -4 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
            <input type="checkbox" checked={cleanOnly}
                   onChange={e => setCleanOnly(e.target.checked)} />
            Only fully auto-approved
          </label>
          <a className="btn ghost"
             href={api(`/api/export/csv?limit=${HISTORY_LIMIT}&only_clean=${cleanOnly}`)}
             title="One row per line item, ready for a QuickBooks / Zoho / Tally 'Import Bills' screen">
            Export CSV
          </a>
          <a className="btn ghost"
             href={api(`/api/export/tally?limit=${HISTORY_LIMIT}&only_clean=${cleanOnly}`)}
             title="Tally's native voucher-import XML — Gateway of Tally > Import Data. Ledger names must already exist in your Tally company.">
            Export Tally XML
          </a>
        </div>
      )}

      {q.trim() && shown.length > 0 && (
        <p className="listcount">{shown.length} of {docs.length} documents</p>
      )}

      {shown.length === 0 && (
        <div className="empty-state">
          <span className="ico"><IconDoc size={22} /></span>
          <h3>{q.trim() ? 'No file name matches that' : 'Nothing processed yet'}</h3>
          {q.trim() ? (
            <p>
              No invoice is called <strong>{q.trim()}</strong>. This box only searches
              file names — to search <em>inside</em> an invoice for a GSTIN, a total or
              a date, open the invoice and use the search on that screen.
            </p>
          ) : (
            <p>
              Upload some invoices and they will appear here, with what each one cost
              and how long it took.
            </p>
          )}
          {q.trim() && <button className="btn ghost" onClick={() => setQ('')}>Show all documents</button>}
        </div>
      )}

      <div className="doclist">
        {shown.map((d, i) => (
          <div key={d.id}
               className={`docrow ${d.id === activeId ? 'active' : ''}`}
               style={{ animationDelay: `${Math.min(i, 12) * 28}ms` }}>
            <button className="docrow-main" onClick={() => onOpen(d)} title={d.filename}>
              <span className="docrow-name">{d.filename}</span>
              <span className="docrow-meta">
                {new Date(d.created_at).toLocaleString('en-IN', {
                  day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
                })}
                {d.total_ms ? ` · ${ms(d.total_ms)}` : ''}
                {/* free and unknown are different states and must not collapse */}
                {d.cost_usd === null || d.cost_usd === undefined
                  ? ''
                  : ` · ${d.cost_usd === 0 ? 'free' : usd(d.cost_usd)}`}
              </span>
            </button>

            <span className={`badge ${d.auto_accept_rate >= 0.85 ? 'green' : 'amber'}`}>
              {Math.round(d.auto_accept_rate * 100)}% auto
            </span>

            {confirmId === d.id ? (
              <span className="rowconfirm">
                delete?
                <button className="linkbtn danger" disabled={deletingId === d.id}
                        onClick={() => { setConfirmId(null); onDelete(d.id) }}>yes</button>
                <button className="linkbtn" onClick={() => setConfirmId(null)}>no</button>
              </span>
            ) : (
              <button className="linkbtn danger" title="Delete this record"
                      onClick={() => setConfirmId(d.id)}>delete</button>
            )}
          </div>
        ))}
      </div>
    </>
  )
}

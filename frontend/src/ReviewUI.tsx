import { useState } from 'react'
import type { Cost, ExtractionResult, FieldResult, Timing } from './types'
import { FIELD_LABELS } from './types'

/* Shared between the live batch queue and the history browser — a processed
   invoice looks the same whether it just finished or was pulled back out of
   Supabase five minutes later. */

export const confColor = (c: number) => (c >= 0.85 ? 'var(--green)' : c >= 0.6 ? 'var(--amber)' : 'var(--red)')
export const statusIcon = (s: string) => (s === 'auto_accept' ? '✓' : s === 'review' ? '!' : '✕')

export function fmt(v: string | number | null): string {
  if (v === null || v === '') return '—'
  if (typeof v === 'number') return v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return v
}

export function reviewCount(r: ExtractionResult): number {
  return r.fields.filter(f => f.status !== 'auto_accept' && f.value !== null).length
}

/** Sub-second work is noise at second-precision, so keep ms until it isn't. */
export function ms(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return v < 1000 ? `${Math.round(v)}ms` : `${(v / 1000).toFixed(1)}s`
}

/* Per-document costs on cheap models land around $0.0002, so two decimal
   places would render every invoice as "$0.00" and tell you nothing. Small
   amounts keep four places; only real money rounds to cents. */
export function usd(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  if (v === 0) return '$0'
  if (v < 0.01) return `$${v.toFixed(4)}`
  return `$${v.toFixed(2)}`
}

/** The three states must stay visibly distinct: free, unknown, and priced. */
export function costLabel(c: Cost | undefined): { text: string; tone?: string } {
  if (!c) return { text: '—' }
  if (!c.known) return { text: 'partly unknown', tone: 'amber' }
  if (c.free) return { text: 'free tier' }
  return { text: `${usd(c.total_usd)}${c.is_estimated ? '*' : ''}`, tone: 'amber' }
}

export function TimingPanel({ t, c }: { t: Timing; c?: Cost }) {
  const [open, setOpen] = useState(false)
  const serial = t.calls.reduce((s, c) => s + c.latency_ms, 0)
  const wasted = t.calls.reduce((s, c) => s + c.wasted_ms, 0)
  const retried = t.calls.filter(c => c.attempts > 1)

  return (
    <div className="timing">
      <button className="linkbtn" data-open={open ? '1' : '0'}
              onClick={() => setOpen(o => !o)}>
        {open ? 'Hide timing' : 'Timing breakdown'}
      </button>
      {open && (
        <div className="timing-body">
          <div className="timing-phases">
            <span>parse <strong>{ms(t.parse_ms)}</strong></span>
            <span>extract <strong>{ms(t.llm_ms)}</strong></span>
            <span>scoring <strong>{ms(t.scoring_ms)}</strong></span>
            <span>save <strong>{ms(t.db_ms)}</strong></span>
            <span>total <strong>{ms(t.total_ms)}</strong></span>
          </div>

          <div className="tablewrap">
          <table className="timing-table">
            <thead>
              <tr>
                <th>Pass</th><th>Provider</th><th>Model</th>
                <th className="num">Latency</th><th className="num">Tries</th>
                <th className="num">Lost to retries</th>
                <th className="num">Tokens</th><th className="num">Cost</th>
              </tr>
            </thead>
            <tbody>
              {t.calls.map(c => (
                <tr key={c.pass_index}>
                  <td>{c.pass_index + 1}</td>
                  <td>{c.provider}</td>
                  <td className="dim">{c.model}</td>
                  <td className="num">{ms(c.latency_ms)}</td>
                  <td className="num">{c.attempts}</td>
                  <td className="num">{c.wasted_ms > 0 ? ms(c.wasted_ms) : '—'}</td>
                  <td className="num">
                    {c.prompt_tokens === null ? '—'
                      : `${c.prompt_tokens}/${c.completion_tokens ?? 0}`}
                  </td>
                  <td className="num">
                    {c.cost_usd === null ? 'n/r' : usd(c.cost_usd)}
                    {c.cost_is_estimated && '*'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>

          {/* The passes overlap, so the phase total is smaller than the sum of
              the calls. Saying so is the whole point of showing both. */}
          {t.calls.length > 1 && (
            <p className="timing-note">
              The {t.calls.length} passes ran concurrently: {ms(serial)} of model time
              finished in {ms(t.llm_ms)} of real time.
            </p>
          )}
          {retried.length > 0 && (
            <p className="timing-note warnish">
              {ms(wasted)} of that was spent being refused by a provider and retrying —
              not extracting. That is a rate-limit problem, not a slow model.
            </p>
          )}
          {c && (
            <p className="timing-note">
              {c.prompt_tokens.toLocaleString()} tokens in,{' '}
              {c.completion_tokens.toLocaleString()} out across {t.calls.length} pass
              {t.calls.length === 1 ? '' : 'es'}
              {c.free && ' — every pass reported $0, so this ran entirely on free tier.'}
              {!c.free && c.known && ` — ${usd(c.total_usd)} total.`}
            </p>
          )}
          {c?.is_estimated && (
            <p className="timing-note">
              * Estimated from the price table in <code>MODEL_PRICING_USD_PER_MTOK</code>,
              not a figure the provider billed. Treat it as indicative.
            </p>
          )}
          {c && !c.known && (
            <p className="timing-note warnish">
              At least one provider returned no price, marked <code>n/r</code> above.
              The total is therefore a floor, not the full cost — it is reported as
              unknown rather than assumed to be zero.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export function Stat({ k, v, tone, small }: { k: string; v: string; tone?: string; small?: boolean }) {
  return (
    <div className="stat">
      <div className="k">{k}</div>
      <div className={`v ${tone ?? ''}`} style={small ? { fontSize: 14, fontWeight: 500, wordBreak: 'break-all' } : undefined}>{v}</div>
    </div>
  )
}

export function Detail({ result, corrected, onSave, readOnly, fields }: {
  result: ExtractionResult
  corrected: Record<string, string>
  onSave: (docId: string | undefined, f: FieldResult, value: string) => void
  readOnly?: boolean
  /* The desktop canvas filters and searches the field list. The summary stats
     above deliberately keep counting the WHOLE document — a filter narrows what
     you are looking at, it does not change what the invoice actually scored. */
  fields?: FieldResult[]
}) {
  const shown = fields ?? result.fields
  const needsReview = shown.filter(f => f.status !== 'auto_accept')
  const autoOk = shown.filter(f => f.status === 'auto_accept')

  return (
    <>
      {result.warnings.map((w, i) => <div className="warn" key={i}>{w}</div>)}

      <div className="summary">
        <Stat k="File" v={result.filename} small />
        <Stat k="Read as" v={result.source === 'ocr_image' ? 'scan / photo' : 'text PDF'} small />
        <Stat k="Auto-approved" v={`${Math.round(result.auto_accept_rate * 100)}%`}
              tone={result.auto_accept_rate >= 0.7 ? 'green' : 'amber'} />
        <Stat k="Needs a human" v={String(reviewCount(result))}
              tone={reviewCount(result) ? 'amber' : 'green'} />
        <Stat k="Mean confidence" v={result.overall_confidence.toFixed(2)}
              tone={result.overall_confidence >= 0.85 ? 'green' : 'amber'} />
        {result.timing && result.timing.total_ms > 0 && (
          <Stat k="Took" v={ms(result.timing.total_ms)} />
        )}
        {result.cost && (result.cost.prompt_tokens > 0 || !result.cost.known) && (
          <Stat k="Cost" {...(() => {
            const l = costLabel(result.cost)
            return { v: l.text, tone: l.tone, small: l.text.length > 8 }
          })()} />
        )}
      </div>

      {result.timing && result.timing.calls.length > 0 &&
        <TimingPanel t={result.timing} c={result.cost} />}

      {needsReview.length > 0 && (
        <>
          <div className="section-title">Needs your eyes ({needsReview.length})</div>
          {needsReview.map(f => (
            <Field key={f.name} f={f} corrected={corrected[f.name]} readOnly={readOnly}
                   onSave={(field, v) => onSave(result.document_id ?? undefined, field, v)} defaultOpen />
          ))}
        </>
      )}

      {autoOk.length > 0 && (
        <>
          <div className="section-title">Auto-accepted ({autoOk.length})</div>
          {autoOk.map(f => (
            <Field key={f.name} f={f} corrected={corrected[f.name]} readOnly={readOnly}
                   onSave={(field, v) => onSave(result.document_id ?? undefined, field, v)} />
          ))}
        </>
      )}

      {result.line_items.length > 0 && (
        <>
          <div className="section-title">Line items</div>
          <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>Description</th><th>HSN/SAC</th>
                <th className="num">Qty</th><th className="num">Rate</th><th className="num">Amount</th>
              </tr>
            </thead>
            <tbody>
              {result.line_items.map((li, i) => (
                <tr key={i}>
                  <td>{li.description ?? '—'}</td>
                  <td>{li.hsn_sac ?? '—'}</td>
                  <td className="num">{li.quantity ?? '—'}</td>
                  <td className="num">{fmt(li.unit_price)}</td>
                  <td className="num">{fmt(li.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </>
      )}

      <p className="muted" style={{ marginTop: 22 }}>
        Extracted via <strong>{result.provider}</strong>
        {result.document_id
          ? <> · saved as <code>{result.document_id.slice(0, 8)}</code>{!readOnly && ' — your corrections are stored as training data'}</>
          : <> · not saved (Supabase is not configured, so corrections stay in this browser tab)</>}
      </p>
    </>
  )
}

export function Field({ f, corrected, onSave, defaultOpen, readOnly }: {
  f: FieldResult
  corrected?: string
  onSave: (f: FieldResult, value: string) => void
  defaultOpen?: boolean
  readOnly?: boolean
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(f.value === null ? '' : String(f.value))
  const [open, setOpen] = useState(!!defaultOpen)

  const isCorrected = corrected !== undefined
  const shown = isCorrected ? corrected : f.value

  const commit = () => {
    setEditing(false)
    if (draft !== (f.value === null ? '' : String(f.value))) onSave(f, draft)
  }

  return (
    <div className={`field ${isCorrected ? 'corrected' : f.status}`}>
      <div className="field-top">
        <span className="icon" style={{ color: isCorrected ? 'var(--accent)' : confColor(f.confidence) }}>
          {isCorrected ? '✎' : statusIcon(f.status)}
        </span>
        <span className="field-label">{FIELD_LABELS[f.name] ?? f.name}</span>

        {editing ? (
          <input
            autoFocus value={draft}
            onChange={e => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={e => {
              if (e.key === 'Enter') commit()
              if (e.key === 'Escape') { setDraft(f.value === null ? '' : String(f.value)); setEditing(false) }
            }}
          />
        ) : (
          <span
            className={`field-value ${shown === null || shown === '' ? 'empty' : ''}`}
            onDoubleClick={() => { if (!readOnly) setEditing(true) }}
          >
            {fmt(shown as string | number | null)}
          </span>
        )}

        {!editing && !readOnly && (
          <button className="linkbtn" onClick={() => setEditing(true)}>
            {isCorrected ? 'edit' : 'correct'}
          </button>
        )}

        <div className="conf" title={`${Math.round(f.confidence * 100)}% confident`}>
          <div className="bar">
            <i style={{ width: `${Math.max(f.confidence * 100, 2)}%`, background: confColor(f.confidence) }} />
          </div>
          <span className="conf-num" style={{ color: confColor(f.confidence) }}>
            {Math.round(f.confidence * 100)}%
          </span>
        </div>

        <button className="linkbtn" onClick={() => setOpen(o => !o)}>{open ? 'hide' : 'why'}</button>
      </div>

      {open && (
        <div className="why">
          <div className="signals">
            <span>self-reported <strong>{f.self_reported.toFixed(2)}</strong></span>
            <span>agreement <strong>{f.agreement.toFixed(2)}</strong></span>
            <span>rules <strong>{f.rules.toFixed(2)}</strong></span>
          </div>
          {f.rule_notes.length > 0 && <ul>{f.rule_notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
        </div>
      )}
    </div>
  )
}

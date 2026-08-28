import { useRef, useState } from 'react'
import type { BatchItem, FieldResult } from '../types'
import { Detail, ms, reviewCount, usd } from '../ReviewUI'
import { FieldTools, NoFieldsMatch, filterFields, type FieldFilter } from './FieldTools'
import { IconAlert, IconUpload } from './Icons'

/* Mobile Upload: drop target on top, then the queue, then the extracted data
   for whichever item you tap. One column, because a phone has no room for a
   list and a detail pane side by side and pretending otherwise gives you two
   cramped columns instead of one usable one. */

export default function UploadView({
  batch, activeId, corrections, onFiles, onSelect, onSave,
  fieldQ, fieldFilter, onFieldQ, onFieldFilter,
}: {
  batch: BatchItem[]
  activeId: string | null
  corrections: Record<string, Record<string, string>>
  onFiles: (files: FileList | File[]) => void
  onSelect: (id: string) => void
  onSave: (docId: string | undefined, f: FieldResult, value: string) => void
  fieldQ: string
  fieldFilter: FieldFilter
  onFieldQ: (v: string) => void
  onFieldFilter: (v: FieldFilter) => void
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)

  const active = batch.find(b => b.id === activeId)
  const done = batch.filter(b => b.status === 'done')
  const busy = batch.filter(b => b.status === 'queued' || b.status === 'processing').length
  const failed = batch.filter(b => b.status === 'error').length
  const needing = done.reduce((s, b) => s + (b.result ? reviewCount(b.result) : 0), 0)

  const times = done.map(b => b.result?.timing?.total_ms ?? 0).filter(t => t > 0)
  const avgMs = times.length ? times.reduce((a, b) => a + b, 0) / times.length : 0

  // Only sum documents whose cost is fully known; a partial figure presented as
  // a total understates the batch while looking authoritative.
  const costs = done.map(b => b.result?.cost).filter(Boolean)
  const known = costs.filter(c => c!.known)
  const batchUsd = known.reduce((s, c) => s + c!.total_usd, 0)
  const allFree = known.length > 0 && known.every(c => c!.free)
  const partial = costs.length !== known.length

  return (
    <>
      <div
        className={`mobile-drop ${over ? 'over' : ''}`}
        onDragOver={e => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={e => {
          e.preventDefault(); setOver(false)
          if (e.dataTransfer.files?.length) onFiles(e.dataTransfer.files)
        }}
      >
        <span className="empty-state-ico"><IconUpload size={22} /></span>
        <h2>{batch.length ? 'Add more invoices' : 'Drop your invoices here'}</h2>
        <p>
          PDF, PNG or JPG — scans and phone photos included. As many at once as you like,
          up to 20 MB each.
        </p>
        <input
          ref={fileRef} type="file" hidden multiple
          accept=".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.txt"
          onChange={e => { if (e.target.files?.length) onFiles(e.target.files); e.target.value = '' }}
        />
        <button className="btn" onClick={() => fileRef.current?.click()}>Choose files</button>
      </div>

      {batch.length > 0 && (
        <div className="summary">
          <div className="stat"><div className="k">Uploaded</div><div className="v">{batch.length}</div></div>
          <div className="stat">
            <div className="k">In flight</div>
            <div className={`v ${busy ? 'amber' : ''}`}>{busy}</div>
          </div>
          <div className="stat"><div className="k">Done</div><div className="v green">{done.length}</div></div>
          <div className="stat">
            <div className="k">Needs a human</div>
            <div className={`v ${needing ? 'amber' : 'green'}`}>{needing}</div>
          </div>
          {failed > 0 && (
            <div className="stat"><div className="k">Failed</div><div className="v red">{failed}</div></div>
          )}
          {times.length > 0 && (
            <div className="stat">
              <div className="k">Average</div>
              <div className="v" style={{ fontSize: 19 }}>{ms(avgMs)}</div>
            </div>
          )}
          {costs.length > 0 && (
            <div className="stat">
              <div className="k">{partial ? 'Batch cost (partial)' : 'Batch cost'}</div>
              <div className={`v ${batchUsd > 0 || partial ? 'amber' : ''}`} style={{ fontSize: 19 }}>
                {allFree && !partial ? 'free tier' : usd(batchUsd)}
              </div>
            </div>
          )}
        </div>
      )}

      {batch.length > 0 && (
        <>
          <div className="section-title">This batch</div>
          <div className="doclist">
            {batch.map((item, i) => (
              <div key={item.id}
                   className={`docrow ${item.id === activeId ? 'active' : ''}`}
                   style={{ animationDelay: `${Math.min(i, 12) * 28}ms` }}>
                <button className="docrow-main" onClick={() => onSelect(item.id)}>
                  <span className="docrow-name">{item.file.name}</span>
                  <span className="docrow-meta">
                    {item.status === 'queued' && 'waiting'}
                    {item.status === 'processing' && 'extracting…'}
                    {item.status === 'done' && item.result &&
                      `${ms(item.result.timing?.total_ms)} · ${Math.round(item.result.auto_accept_rate * 100)}% auto`}
                    {item.status === 'error' && (item.error ?? 'failed')}
                  </span>
                </button>
                {item.status === 'processing' && <span className="spinner" style={{ margin: 0 }} />}
                {item.status === 'done' && item.result && (
                  <span className={`badge ${reviewCount(item.result) ? 'amber' : 'green'}`}>
                    {reviewCount(item.result) ? `${reviewCount(item.result)} to check` : 'all clear'}
                  </span>
                )}
                {item.status === 'error' && (
                  <span className="badge red"><IconAlert size={12} /></span>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {active?.status === 'error' && (
        <div className="err" style={{ marginTop: 16 }}>
          <strong>Extraction failed for {active.file.name}.</strong> {active.error}
        </div>
      )}

      {active?.status === 'done' && active.result && (
        <div style={{ marginTop: 20 }}>
          {/* Same search and filter as everywhere else. A freshly extracted
              invoice is exactly where you most want to jump straight to the
              flagged fields. */}
          <FieldTools q={fieldQ} filter={fieldFilter} onQ={onFieldQ} onFilter={onFieldFilter} />
          <Detail
            result={active.result}
            corrected={corrections[active.result.document_id ?? ''] ?? {}}
            onSave={onSave}
            fields={filterFields(active.result.fields, fieldQ, fieldFilter)}
          />
          {filterFields(active.result.fields, fieldQ, fieldFilter).length === 0 &&
            <NoFieldsMatch filter={fieldFilter} q={fieldQ} />}
        </div>
      )}
    </>
  )
}

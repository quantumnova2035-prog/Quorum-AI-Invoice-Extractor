import type { FieldResult } from '../types'
import { FIELD_LABELS } from '../types'
import { SearchBox, Segmented } from './Toolbar'

/* Searching inside an open invoice has to work the same on a phone as on a
   desktop. It was desktop-only because the toolbar was built into the desktop
   canvas; pulling it out here means both layouts drive the same filter with the
   same rules, rather than one of them silently having no search at all. */

export type FieldFilter = 'all' | 'review' | 'accepted'

export const FIELD_FILTERS: { id: FieldFilter; label: string }[] = [
  { id: 'all',      label: 'All' },
  { id: 'review',   label: 'Needs review' },
  { id: 'accepted', label: 'Auto-accepted' },
]

/** Match the visible label as well as the raw key: the screen says "Vendor
    GSTIN", so typing that must work even though the field is `vendor_gstin`.
    Rule notes are searchable too, so you can pull up every field that tripped
    the same check - "future", "arithmetic", "checksum". */
export function filterFields(
  fields: FieldResult[], q: string, filter: FieldFilter,
): FieldResult[] {
  const needle = q.trim().toLowerCase()
  return fields.filter(f => {
    if (filter === 'review' && f.status === 'auto_accept') return false
    if (filter === 'accepted' && f.status !== 'auto_accept') return false
    if (!needle) return true
    return (FIELD_LABELS[f.name] ?? f.name).toLowerCase().includes(needle)
      || f.name.toLowerCase().includes(needle)
      || String(f.value ?? '').toLowerCase().includes(needle)
      || f.rule_notes.some(n => n.toLowerCase().includes(needle))
  })
}

export function FieldTools({ q, filter, onQ, onFilter, className }: {
  q: string
  filter: FieldFilter
  onQ: (v: string) => void
  onFilter: (v: FieldFilter) => void
  className?: string
}) {
  return (
    <div className={className ?? 'listtools'}>
      <SearchBox value={q} onChange={onQ}
                 placeholder="Search this invoice — field, value, or why it was flagged…" />
      <Segmented value={filter} options={FIELD_FILTERS} onChange={onFilter}
                 label="Filter fields" />
    </div>
  )
}

/** Shown when a filter or search leaves nothing - so an empty list reads as
    "nothing matched" rather than "this invoice has no fields". */
export function NoFieldsMatch({ filter, q }: { filter: FieldFilter; q: string }) {
  return (
    <div className="empty-state">
      <h3>No fields match</h3>
      <p>
        {filter === 'review' && !q.trim()
          ? 'Every field on this invoice was auto-accepted — there is nothing needing a human here.'
          : filter === 'accepted' && !q.trim()
            ? 'Nothing on this invoice was auto-accepted.'
            : 'Try a shorter search, or switch the filter back to All.'}
      </p>
    </div>
  )
}

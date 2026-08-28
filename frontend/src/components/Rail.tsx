import type { DeskDoc } from '../types'
import { IconChevrons, IconClose } from './Icons'

/* The sidebar holds open documents as closeable tabs. Opening a document from
   the dock adds a tab; closing one removes it without deleting anything - the
   document itself still lives in the dock and in Supabase. That distinction
   matters: a close button that destroyed data would be the same gesture people
   use dozens of times a day to tidy their workspace. */

export default function Rail({ tabs, activeId, collapsed, onSelect, onClose, onToggle }: {
  tabs: DeskDoc[]
  activeId: string | null
  collapsed: boolean
  onSelect: (id: string) => void
  onClose: (id: string) => void
  onToggle: () => void
}) {
  return (
    <aside className="rail" aria-label="Open documents">
      <div className="rail-head">
        <span className="t">Open · {tabs.length}</span>
        <button
          className={`iconbtn ${collapsed ? 'flip' : ''}`}
          onClick={onToggle}
          aria-label={collapsed ? 'Show open documents' : 'Hide open documents'}
          title={collapsed ? 'Show open documents' : 'Hide open documents'}
        >
          <IconChevrons />
        </button>
      </div>

      <div className="rail-body">
        {tabs.length === 0 && (
          <p className="rail-empty">
            No documents open. Pick one from the stack above to open it here.
          </p>
        )}
        {tabs.map((t, i) => (
          <div
            key={t.id}
            className={`tabchip ${t.id === activeId ? 'active' : ''}`}
            style={{ animationDelay: `${Math.min(i, 8) * 30}ms` }}
            onClick={() => onSelect(t.id)}
            role="button"
            tabIndex={0}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(t.id) } }}
            title={t.filename}
          >
            <span className="label">{t.filename}</span>
            <button
              className="tabclose"
              aria-label={`Close ${t.filename}`}
              /* Stop the click reaching the chip, or closing a tab would select
                 it on the way out and flash the wrong document into the canvas. */
              onClick={e => { e.stopPropagation(); onClose(t.id) }}
            >
              <IconClose />
            </button>
          </div>
        ))}
      </div>
    </aside>
  )
}

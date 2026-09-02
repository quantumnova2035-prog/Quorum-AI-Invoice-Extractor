import { useEffect, useRef, useState } from 'react'
import {
  BYO_MODELS, byoActive, maskKey, priceLabel, type ByoSettings,
} from '../byok'

/* One panel, two homes: a dialog behind the provider chip on desktop, a section
   of Settings on mobile. Written once, because three copies of a search box is
   exactly how this codebase ended up with three different search behaviours. */
export function ByoPanel({ value, onChange }: {
  value: ByoSettings
  onChange: (v: ByoSettings) => void
}) {
  const [reveal, setReveal] = useState(false)
  const active = byoActive(value)
  const hasKey = value.key.trim().length > 0

  return (
    <div className="byo">
      <div className="byo-toggle">
        <div>
          <div className="byo-toggle-t">Use my own key</div>
          <div className="byo-toggle-s">
            {/* Enabled-but-empty is its own state. Saying "runs on the project's
                chain" under a switch that is visibly ON reads as a bug in the
                switch, when the truth is simply that there is nothing to use
                yet. */}
            {active ? 'Your key and model are used for every extraction.'
              : value.enabled ? 'Add your key below — until then, the project’s own chain is used.'
              : "Extractions run on the project's own free-tier chain."}
          </div>
        </div>
        <button
          role="switch" aria-checked={value.enabled}
          className={`switch${value.enabled ? ' on' : ''}`}
          onClick={() => onChange({ ...value, enabled: !value.enabled })}
        >
          <i />
        </button>
      </div>

      {value.enabled && (
        <div className="byo-body">
          <label className="byo-label" htmlFor="byo-key">OpenRouter API key</label>
          <div className="byo-keyrow">
            <input
              id="byo-key"
              className="byo-input mono"
              type={reveal ? 'text' : 'password'}
              autoComplete="off" spellCheck={false}
              placeholder="sk-or-v1-…"
              value={value.key}
              onChange={e => onChange({ ...value, key: e.target.value })}
            />
            <button className="btn ghost" onClick={() => setReveal(r => !r)}>
              {reveal ? 'Hide' : 'Show'}
            </button>
          </div>
          {hasKey && !reveal && (
            <p className="byo-hint mono">{maskKey(value.key)}</p>
          )}

          <div className="byo-label" style={{ marginTop: 16 }}>Model</div>
          <div className="byo-models" role="radiogroup" aria-label="Model">
            {BYO_MODELS.map(m => (
              <button
                key={m.id} role="radio" aria-checked={value.model === m.id}
                className={`byo-model${value.model === m.id ? ' on' : ''}`}
                onClick={() => onChange({ ...value, model: m.id })}
              >
                <span className="byo-model-main">
                  <span className="byo-model-name">{m.label}</span>
                  <span className="byo-model-id mono">{m.id}</span>
                </span>
                <span className="byo-model-meta">
                  <span className={`byo-price${m.input === null ? ' free' : ''}`}>
                    {priceLabel(m)}
                  </span>
                  <span className="byo-ctx mono">{m.context}</span>
                </span>
              </button>
            ))}
          </div>
          <p className="byo-note">
            Prices are per 1M tokens, in / out, as published by OpenRouter — shown to
            help you choose. What the app records as cost is always the figure
            OpenRouter reports for the request itself, never this table.
          </p>
          <p className="byo-note">
            If you upload a scan or photo, pick a model that accepts images. A
            text-only model will be refused by OpenRouter rather than guessing.
          </p>
          <p className="byo-note byo-note-key">
            Your key is stored in this browser only. It is sent with each extraction
            and passes through the server to reach OpenRouter — it is never written
            to the database, never logged, and redacted out of any error message.
          </p>
        </div>
      )}
    </div>
  )
}

/* Desktop presentation. Escape closes, the backdrop closes, focus moves in on
   open and the dialog is labelled - a panel that traps someone with no way back
   to the page is worse than no panel. */
export function ByoDialog({ open, onClose, value, onChange }: {
  open: boolean
  onClose: () => void
  value: ByoSettings
  onChange: (v: ByoSettings) => void
}) {
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    panel.current?.querySelector<HTMLElement>('input, button')?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="byo-backdrop" onMouseDown={e => {
      if (e.target === e.currentTarget) onClose()
    }}>
      <div className="byo-dialog" ref={panel} role="dialog" aria-modal="true"
           aria-labelledby="byo-title">
        <div className="byo-dialog-head">
          <h2 id="byo-title">Provider</h2>
          <button className="iconbtn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="byo-dialog-body">
          <ByoPanel value={value} onChange={onChange} />
        </div>
      </div>
    </div>
  )
}

import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import { IconClose, IconSearch } from './Icons'

/* Segmented control. Same principle as the mobile nav: one thumb that slides,
   measured from real geometry, because the options have different label widths
   and an assumed slot width drifts visibly. */
export function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T
  options: { id: T; label: string }[]
  onChange: (v: T) => void
  label: string
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})
  const wrapRef = useRef<HTMLDivElement>(null)
  const [thumb, setThumb] = useState<{ x: number; w: number } | null>(null)

  const measure = useCallback(() => {
    const el = refs.current[value]
    if (!el) return
    setThumb({ x: el.offsetLeft, w: el.offsetWidth })
  }, [value])

  useLayoutEffect(measure, [measure])
  useLayoutEffect(() => {
    const ro = new ResizeObserver(measure)
    if (wrapRef.current) ro.observe(wrapRef.current)
    return () => ro.disconnect()
  }, [measure])

  return (
    <div className="seg" ref={wrapRef} role="group" aria-label={label}>
      {thumb && (
        <span className="thumb" style={{ width: thumb.w, transform: `translateX(${thumb.x}px)` }} />
      )}
      {options.map(o => (
        <button
          key={o.id}
          ref={el => { refs.current[o.id] = el }}
          className={value === o.id ? 'on' : ''}
          aria-pressed={value === o.id}
          onClick={() => onChange(o.id)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function SearchBox({ value, onChange, placeholder }: {
  value: string
  onChange: (v: string) => void
  placeholder: string
}) {
  return (
    <div className="search">
      <IconSearch />
      <input
        type="search"
        value={value}
        placeholder={placeholder}
        onChange={e => onChange(e.target.value)}
        /* Escape clears without leaving the field - the fastest way back to the
           full list when the filter was a dead end. */
        onKeyDown={e => { if (e.key === 'Escape' && value) { e.preventDefault(); onChange('') } }}
      />
      {value && (
        <button className="clear" onClick={() => onChange('')} aria-label="Clear search">
          <IconClose size={12} />
        </button>
      )}
    </div>
  )
}

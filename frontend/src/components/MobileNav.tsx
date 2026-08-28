import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import { IconHome, IconSettings, IconUpload } from './Icons'

export type View = 'home' | 'upload' | 'settings'

const ITEMS: { id: View; label: string; Icon: typeof IconHome }[] = [
  { id: 'home',     label: 'Home',     Icon: IconHome },
  { id: 'upload',   label: 'Upload',   Icon: IconUpload },
  { id: 'settings', label: 'Settings', Icon: IconSettings },
]

/* The active indicator is ONE element that slides between slots, positioned
   from the real measured geometry rather than an assumed item width. Labels
   differ in length, so any hardcoded 33%-per-slot maths would drift - and a
   pill that sits a few pixels off its label is the kind of thing you feel
   without being able to name it.

   Two separate backgrounds cross-fading would also be wrong: it reads as one
   thing vanishing and another appearing, not as a single object moving. */
export default function MobileNav({ view, onChange, badge }: {
  view: View
  onChange: (v: View) => void
  badge?: number
}) {
  const barRef = useRef<HTMLElement>(null)
  const itemRefs = useRef<Record<string, HTMLButtonElement | null>>({})
  const [thumb, setThumb] = useState<{ x: number; w: number } | null>(null)

  const measure = useCallback(() => {
    const bar = barRef.current
    const el = itemRefs.current[view]
    if (!bar || !el) return
    setThumb({ x: el.offsetLeft, w: el.offsetWidth })
  }, [view])

  // Layout effect, not effect: measuring after paint would show the thumb at
  // its old slot for one frame on first render.
  useLayoutEffect(measure, [measure])

  useLayoutEffect(() => {
    const ro = new ResizeObserver(measure)
    if (barRef.current) ro.observe(barRef.current)
    return () => ro.disconnect()
  }, [measure])

  return (
    <nav className="mobilenav" ref={barRef} aria-label="Primary">
      {thumb && (
        <span
          className="navthumb"
          style={{ width: thumb.w, transform: `translateX(${thumb.x}px)` }}
        />
      )}
      {ITEMS.map(({ id, label, Icon }) => (
        <button
          key={id}
          ref={el => { itemRefs.current[id] = el }}
          className={`navitem ${view === id ? 'on' : ''}`}
          aria-current={view === id ? 'page' : undefined}
          onClick={() => onChange(id)}
        >
          <Icon />
          <span>{label}</span>
          {id === 'home' && !!badge && <i className="navdot" aria-hidden />}
        </button>
      ))}
    </nav>
  )
}

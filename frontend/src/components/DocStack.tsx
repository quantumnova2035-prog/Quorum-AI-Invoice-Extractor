import { useEffect, useRef, useState } from 'react'
import type { DeskDoc } from '../types'
import { IconAlert, IconPlus } from './Icons'

/* The desktop dock: an upload target, then the documents as a physical stack of
   sheets you pick from. Cards rather than rows because a document is an object
   here - you open it, keep several open at once, and close them again. */

const kindOf = (name: string) => {
  const ext = name.split('.').pop()?.toUpperCase() ?? 'DOC'
  return ext.length > 4 ? 'DOC' : ext
}

export default function DocStack({ docs, activeId, onOpen, onFiles }: {
  docs: DeskDoc[]
  activeId: string | null
  onOpen: (d: DeskDoc) => void
  onFiles: (files: FileList | File[]) => void
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const stackRef = useRef<HTMLDivElement>(null)
  const [over, setOver] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [edges, setEdges] = useState({ left: false, right: false })
  // Set when a drag actually moved, so the click that ends it does not also
  // open whichever card happened to be under the finger.
  const movedRef = useRef(false)
  const glideRef = useRef(0)

  /* Drag to scroll, with the release throwing the stack rather than stopping it
     dead. Three things make this feel physical instead of mechanical:

     1:1 tracking - the stack stays glued to the pointer for the whole drag,
     offset from where it was grabbed, not re-centred on it.

     Velocity handoff - the glide starts at the speed the pointer was already
     moving, so there is no visible seam between dragging and animating.

     Momentum projection - the resting point is projected from that velocity
     using the exponential-decay curve scroll views use, so a flick throws the
     stack proportionally to how hard you flicked it. */
  useEffect(() => {
    const el = stackRef.current
    if (!el) return

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const stopGlide = () => { cancelAnimationFrame(glideRef.current); glideRef.current = 0 }

    let startX = 0
    let startLeft = 0
    let pointer: number | null = null
    // A short history, not just the last point: one sample is noisy, and the
    // final pointermove before release is often a near-zero jitter that would
    // read as "let go while stationary" and kill the throw.
    let samples: { x: number; t: number }[] = []

    const onDown = (e: PointerEvent) => {
      if (e.button !== 0) return
      const max = el.scrollWidth - el.clientWidth
      if (max <= 1) return
      stopGlide()                       // grabbing mid-glide must catch it, not queue behind it
      pointer = e.pointerId
      startX = e.clientX
      startLeft = el.scrollLeft
      samples = [{ x: e.clientX, t: performance.now() }]
      movedRef.current = false
    }

    const onMove = (e: PointerEvent) => {
      if (pointer !== e.pointerId) return
      const dx = e.clientX - startX
      // ~5px of hysteresis before committing, so a click on a card is still a
      // click and not a one-pixel drag.
      if (!movedRef.current && Math.abs(dx) < 5) return
      if (!movedRef.current) {
        movedRef.current = true
        setDragging(true)
        // Capture so the drag survives the pointer leaving the strip.
        el.setPointerCapture(e.pointerId)
      }
      el.scrollLeft = startLeft - dx
      samples.push({ x: e.clientX, t: performance.now() })
      if (samples.length > 6) samples.shift()
    }

    const onUp = (e: PointerEvent) => {
      if (pointer !== e.pointerId) return
      pointer = null
      if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId)
      if (!movedRef.current) return
      setDragging(false)

      const now = performance.now()
      const last = samples[samples.length - 1]
      /* Prefer the last ~150ms of travel. If the pointer only produced one
         sample in that window - a slow drag, a throttled frame - fall back to
         the previous sample rather than reading a single point as "released
         while stationary" and swallowing the throw entirely. A stale pair is
         still rejected: a real pause before release means no throw. */
      let first = samples.filter(s => now - s.t < 150)[0]
      if ((!first || first === last) && samples.length > 1) first = samples[samples.length - 2]

      let velocity = 0                          // px per second, pointer direction
      if (first && last && last.t > first.t && last.t - first.t < 260) {
        velocity = ((last.x - first.x) / (last.t - first.t)) * 1000
      }
      // Scrolling runs opposite the pointer: drag left, content moves right.
      velocity = -velocity
      // Clamp before projecting. Two pointer samples a couple of milliseconds
      // apart produce an enormous derived velocity, and projection multiplies it
      // ~200x - one noisy sample would otherwise fling the strip to the far end.
      velocity = Math.max(-2600, Math.min(2600, velocity))
      if (reduced || Math.abs(velocity) < 80) return

      const decel = 0.995
      const projected = (velocity / 1000) * decel / (1 - decel)
      const max = el.scrollWidth - el.clientWidth
      const target = Math.max(0, Math.min(max, el.scrollLeft + projected))
      const from = el.scrollLeft
      const distance = target - from
      if (Math.abs(distance) < 1) return

      const duration = Math.min(900, Math.max(240, Math.abs(distance) * 1.1))
      const started = performance.now()
      const step = () => {
        const t = Math.min(1, (performance.now() - started) / duration)
        // Quartic ease-out: fast off the release, settling gently - the shape a
        // thrown object decelerating actually has.
        el.scrollLeft = from + distance * (1 - Math.pow(1 - t, 4))
        if (t < 1) glideRef.current = requestAnimationFrame(step)
        else glideRef.current = 0
      }
      glideRef.current = requestAnimationFrame(step)
    }

    /* A drag that ended on a card must not open it. Capture phase, so this runs
       before the card's own handler. */
    const onClickCapture = (e: MouseEvent) => {
      if (!movedRef.current) return
      e.stopPropagation()
      e.preventDefault()
      movedRef.current = false
    }

    el.addEventListener('pointerdown', onDown)
    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerup', onUp)
    el.addEventListener('pointercancel', onUp)
    el.addEventListener('click', onClickCapture, true)
    return () => {
      stopGlide()
      el.removeEventListener('pointerdown', onDown)
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerup', onUp)
      el.removeEventListener('pointercancel', onUp)
      el.removeEventListener('click', onClickCapture, true)
    }
  }, [docs.length])

  /* A vertical wheel over the stack should move it sideways - reaching for a
     scrollbar to browse a row of documents is the wrong gesture entirely.

     Registered by hand rather than via onWheel because React attaches wheel
     listeners passively, and a passive listener cannot preventDefault. Without
     that, the page would scroll at the same time as the stack. */
  useEffect(() => {
    const el = stackRef.current
    if (!el) return

    const onWheel = (e: WheelEvent) => {
      // A trackpad already sends horizontal intent; leave that alone.
      if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return
      const max = el.scrollWidth - el.clientWidth
      if (max <= 1) return
      // Wheeling during a glide should take it over, not fight it.
      cancelAnimationFrame(glideRef.current)
      // At either end, hand the gesture back to the page instead of swallowing
      // it - a container that eats scroll at its boundary feels broken.
      const atStart = el.scrollLeft <= 0 && e.deltaY < 0
      const atEnd = el.scrollLeft >= max - 1 && e.deltaY > 0
      if (atStart || atEnd) return
      e.preventDefault()
      el.scrollLeft += e.deltaY
    }

    const onScroll = () => {
      const max = el.scrollWidth - el.clientWidth
      setEdges({ left: el.scrollLeft > 2, right: max > 2 && el.scrollLeft < max - 2 })
    }

    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('scroll', onScroll, { passive: true })
    const ro = new ResizeObserver(onScroll)
    ro.observe(el)
    onScroll()
    return () => {
      el.removeEventListener('wheel', onWheel)
      el.removeEventListener('scroll', onScroll)
      ro.disconnect()
    }
  }, [docs.length])

  return (
    <div
      className="dock"
      onDragOver={e => { e.preventDefault(); setOver(true) }}
      onDragLeave={() => setOver(false)}
      onDrop={e => {
        e.preventDefault(); setOver(false)
        if (e.dataTransfer.files?.length) onFiles(e.dataTransfer.files)
      }}
    >
      <button
        className={`dock-drop ${over ? 'over' : ''}`}
        onClick={() => fileRef.current?.click()}
      >
        <IconPlus />
        Upload
        <small>or drop files</small>
      </button>
      <input
        ref={fileRef} type="file" hidden multiple
        accept=".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.txt"
        onChange={e => { if (e.target.files?.length) onFiles(e.target.files); e.target.value = '' }}
      />

      {/* Fading edges rather than a scrollbar: with the bar hidden, something
          still has to say there is more in that direction. */}
      <div className={`dock-scroll ${edges.left ? 'fade-l' : ''} ${edges.right ? 'fade-r' : ''}`}>
        <div className={`dock-stack ${dragging ? 'dragging' : ''}`} ref={stackRef}>
          {docs.length === 0 && (
            <p className="dock-empty">
              Nothing here yet. Drop invoices on the left and they will stack up here.
            </p>
          )}
          {docs.map((d, i) => (
            <button
              key={d.id}
              className={`doccard ${d.id === activeId ? 'active' : ''}`
                + (d.status === 'queued' || d.status === 'processing' ? ' is-busy' : '')
                + (d.status === 'error' ? ' is-error' : '')}
              /* Stagger, capped: past ~10 cards the delay stops reading as a
                 cascade and starts reading as lag. */
              style={{ animationDelay: `${Math.min(i, 10) * 35}ms` }}
              onClick={() => onOpen(d)}
              onDragStart={e => e.preventDefault()}
              title={d.filename}
            >
              <span className="card-state">
                {d.status === 'processing' && <span className="spinner" style={{ margin: 0 }} />}
                {d.status === 'error' && <IconAlert className="dim" />}
              </span>
              <span className="kind">{kindOf(d.filename)}</span>
              <span className="name">{d.filename}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

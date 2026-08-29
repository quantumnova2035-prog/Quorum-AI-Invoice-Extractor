import { useEffect, useState } from 'react'
import { WAKE_ESTIMATE_MS } from '../hooks'

const R = 26
const CIRC = 2 * Math.PI * R

/* Past a minute a bare "75" reads as a quantity rather than a duration, and the
   first thing anyone does is stop to work out whether it is seconds. m:ss is
   read, not calculated. */
function clock(ms: number): string {
  const s = Math.ceil(ms / 1000)
  return s >= 60 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}` : String(s)
}

/* Shown only while the API is unreachable, which on the free tier means the
   instance has spun down and is booting.

   The ring carries the message and the words stay out of the way. Someone
   watching a countdown drain does not need a paragraph telling them to wait -
   they need to see that something is counting. The explanation is one tap away
   behind the info button for the minority who want to know why, and it hides
   itself again rather than becoming permanent furniture. */
export function Waking({ elapsed, failed, onRetry }: {
  elapsed: number
  failed: boolean
  onRetry: () => void
}) {
  const [note, setNote] = useState(false)

  // Auto-hide, so a tap out of curiosity does not leave the card permanently
  // taller for the rest of the wait.
  useEffect(() => {
    if (!note) return
    const t = setTimeout(() => setNote(false), 8000)
    return () => clearTimeout(t)
  }, [note])

  const remaining = Math.max(0, WAKE_ESTIMATE_MS - elapsed)
  const over = remaining === 0

  if (failed) {
    return (
      <div className="wakecard is-failed" role="status" aria-live="polite">
        <div className="wakecard-main">
          <div className="wakecard-text">
            <h2>Could not reach the server</h2>
            <p className="wakecard-sub">
              It did not respond after several attempts.
            </p>
          </div>
          <button className="btn" onClick={onRetry}>Try again</button>
        </div>
      </div>
    )
  }

  return (
    <div className="wakecard" role="status" aria-live="polite">
      <div className="wakecard-main">
        <div className={`wakering${over ? ' is-over' : ''}`}>
          <svg viewBox="0 0 64 64" aria-hidden="true">
            <circle className="wr-track" cx="32" cy="32" r={R} />
            <circle
              className="wr-fill" cx="32" cy="32" r={R}
              strokeDasharray={CIRC}
              /* Drains clockwise from full. Past zero this value stops moving
                 and CSS spins the whole ring instead, so the arc never sits
                 frozen at empty pretending the wait is over. */
              strokeDashoffset={CIRC * (1 - remaining / WAKE_ESTIMATE_MS)}
            />
          </svg>
          <span className={`wr-num mono${!over && remaining >= 60_000 ? ' is-long' : ''}`}>
            {over ? '…' : clock(remaining)}
          </span>
        </div>

        <div className="wakecard-text">
          <h2>{over ? 'Almost there' : 'Waking the server'}</h2>
          <p className="wakecard-sub">
            {over ? 'Taking longer than usual. Still trying.' : 'This takes a moment on first visit.'}
          </p>
        </div>

        <button
          className="wakecard-i" onClick={() => setNote(n => !n)}
          aria-expanded={note} aria-label="Why is this happening?"
        >
          i
        </button>
      </div>

      {note && (
        <p className="wakecard-note">
          Free hosting sleeps after 15 minutes of inactivity. Your visit is starting
          it back up. Reloading will not make it faster.
        </p>
      )}
    </div>
  )
}

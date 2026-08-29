import { wakeProgress } from '../hooks'

/* Shown only while the API is actually unreachable, which on the free tier
   means the instance has spun down and is booting. It says three things, in
   this order: something is happening, why it is happening, and how long it has
   been happening. The last one is what stops someone reloading the page - a
   reload does not help, it just starts the wait over from a fresh tab. */
export function Waking({ elapsed, failed, onRetry }: {
  elapsed: number
  failed: boolean
  onRetry: () => void
}) {
  const secs = Math.floor(elapsed / 1000)
  const pct = failed ? 100 : wakeProgress(elapsed) * 100

  return (
    <div className={`wakecard${failed ? ' is-failed' : ''}`} role="status" aria-live="polite">
      <div className="wakecard-head">
        <h2>{failed ? 'Could not reach the server' : 'Waking the server'}</h2>
        {!failed && <span className="wakecard-secs mono">{secs}s</span>}
      </div>

      <p>
        {failed
          ? 'The API did not respond after several attempts. It may still be starting, or it may be down.'
          : 'This demo runs on a free instance that sleeps after 15 minutes of inactivity. Your visit is starting it back up — usually about 30 seconds. Nothing is broken, and reloading will not make it faster.'}
      </p>

      {!failed && (
        <div className="wakecard-bar" aria-hidden="true">
          {/* Approaches full without arriving. It reaches 100% when the server
              answers, not when a guess says it should have. */}
          <i style={{ width: `${pct}%` }} />
        </div>
      )}

      {!failed && secs >= 45 && (
        <p className="wakecard-slow">
          Taking longer than usual. Still trying.
        </p>
      )}

      {failed && (
        <button className="btn" onClick={onRetry}>Try again</button>
      )}
    </div>
  )
}

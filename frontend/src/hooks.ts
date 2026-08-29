import { useCallback, useEffect, useState } from 'react'
import type { DocSummary, ExtractionResult, Health } from './types'
import { api } from './api'

/* The desktop and mobile layouts are not two skins of one tree - one has a
   sidebar of tabs, the other a floating nav and a single column. Trying to do
   that with CSS alone means shipping both DOMs and hiding one, which breaks
   focus order and doubles the work React does. So the breakpoint is a real
   piece of state. */
export function useIsMobile(breakpoint = 980): boolean {
  const query = `(max-width: ${breakpoint}px)`
  const [is, setIs] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(query).matches,
  )
  useEffect(() => {
    const mq = window.matchMedia(query)
    const on = () => setIs(mq.matches)
    on()
    mq.addEventListener('change', on)
    /* `resize` as a backstop. The media-query change event is the correct
       signal and fires on a real window drag, but it does not fire under
       devtools device emulation - and a layout that only switches on reload is
       indistinguishable from a broken one when you are testing it. Setting the
       same value is a no-op in React, so the extra listener costs nothing. */
    window.addEventListener('resize', on)
    return () => {
      mq.removeEventListener('change', on)
      window.removeEventListener('resize', on)
    }
  }, [query])
  return is
}

/** Rows saved before timing/cost existed have no such key, and an empty object
    is not a valid Timing. Both must read as "unknown" rather than render a row
    of confident zeros. */
export function rowToResult(row: Record<string, unknown>): ExtractionResult {
  const t = row.timing as ExtractionResult['timing']
  const c = row.cost as ExtractionResult['cost']
  return {
    document_id: row.id as string,
    filename: row.filename as string,
    source: row.source as string,
    provider: row.provider as string,
    fields: (row.fields ?? []) as ExtractionResult['fields'],
    line_items: (row.line_items ?? []) as ExtractionResult['line_items'],
    overall_confidence: row.overall_confidence as number,
    auto_accept_rate: row.auto_accept_rate as number,
    raw_text_preview: (row.raw_text_preview ?? '') as string,
    warnings: (row.warnings ?? []) as string[],
    timing: t && Array.isArray(t.calls) ? t : undefined,
    cost: c && typeof c.known === 'boolean' ? c : undefined,
  }
}

/* One document's full record, fetched on demand and cached for the session.
   Tabs are opened and closed constantly; re-fetching the same document every
   time it is re-selected would make an instant action feel like a load. */
export function useDocCache() {
  const [cache, setCache] = useState<Record<string, ExtractionResult>>({})
  const [loading, setLoading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchDoc = useCallback(async (id: string) => {
    setError(null)
    setLoading(id)
    try {
      const res = await fetch(api(`/api/documents/${id}`))
      if (!res.ok) {
        throw new Error(res.status === 404
          ? 'Not found - it may have just been deleted.'
          : `HTTP ${res.status}`)
      }
      const row = await res.json()
      setCache(prev => ({ ...prev, [id]: rowToResult(row) }))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(null)
    }
  }, [])

  const ensure = useCallback((id: string) => {
    setCache(prev => {
      if (!prev[id]) void fetchDoc(id)
      return prev
    })
  }, [fetchDoc])

  const put = useCallback((id: string, r: ExtractionResult) => {
    setCache(prev => ({ ...prev, [id]: r }))
  }, [])

  const drop = useCallback((id: string) => {
    setCache(prev => {
      const next = { ...prev }
      delete next[id]
      return next
    })
  }, [])

  return { cache, loading, error, ensure, put, drop, setError }
}

/** Everything ever processed, newest first. Capped, so callers must say so. */
export const HISTORY_LIMIT = 100

export function useHistory() {
  const [docs, setDocs] = useState<DocSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  /* Retries before reporting failure. On a cold start the API is unreachable
     for the first few seconds, and a single attempt would paint "Could not
     reach the server" over a server that is merely still booting - the one
     message guaranteed to make someone close the tab. */
  const load = useCallback(async () => {
    setError(null)
    for (let i = 0; i < 10; i++) {
      try {
        const res = await fetch(api(`/api/documents?limit=${HISTORY_LIMIT}`))
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        setDocs(await res.json())
        return
      } catch {
        await new Promise(r => setTimeout(r, 3000))
      }
    }
    setError('Could not reach the server.')
  }, [])

  useEffect(() => { void load() }, [load])

  return { docs, setDocs, error, reload: load }
}

/* ---------------------------------------------------------- cold start ---- */

/* A free Render instance spins down after 15 minutes idle. The next request
   waits for a container to boot - measured at ~25s against this API, of which
   ~11s is uvicorn importing the app. None of that is an error, but a page that
   sits blank for twenty-five seconds is indistinguishable from a broken one, so
   the wait has to be visible.

   The readout counts UP from zero rather than down to an estimate. A countdown
   that hits zero while the server is still booting is worse than no countdown
   at all - it turns "this is slow" into "this is broken". Elapsed seconds plus a
   bar that approaches full without ever arriving says the reassuring thing
   without making a promise the server has to keep. */
export type WakePhase = 'checking' | 'waking' | 'ready' | 'failed'

/** 0..1, asymptotic - deliberately never reaches 1 until the server answers. */
export function wakeProgress(ms: number): number {
  return Math.min(0.96, 1 - Math.exp(-ms / 14_000))
}

export function useServerWake() {
  const [health, setHealth] = useState<Health | null>(null)
  const [phase, setPhase] = useState<WakePhase>('checking')
  const [elapsed, setElapsed] = useState(0)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    const started = Date.now()
    setPhase('checking')
    setElapsed(0)

    /* One tick drives both the readout and the promotion from "checking" to
       "waking". A warm server answers in ~250ms, so anything still pending at
       2.5s is almost certainly a cold start: long enough that the normal case
       never flashes the banner, short enough to explain the wait before it
       starts to feel like a fault. */
    const tick = setInterval(() => {
      if (cancelled) return
      const ms = Date.now() - started
      setElapsed(ms)
      setPhase(p => (p === 'checking' && ms > 2500 ? 'waking' : p))
    }, 250)

    /* Render usually queues the request against the booting instance, which is
       why a cold start reads as one slow response rather than an error. But the
       edge can also hang up first, and retrying is the entire difference between
       "waking" and a dead end - so failures retry rather than give up. */
    const run = async () => {
      for (let i = 0; i < 12; i++) {
        try {
          const res = await fetch(api('/api/health'))
          if (!res.ok) throw new Error(`HTTP ${res.status}`)
          const json = (await res.json()) as Health
          if (cancelled) return
          setHealth(json)
          setPhase('ready')
          return
        } catch {
          if (cancelled) return
          await new Promise(r => setTimeout(r, 3000))
        }
      }
      if (!cancelled) setPhase('failed')
    }
    void run()

    return () => {
      cancelled = true
      clearInterval(tick)
    }
  }, [attempt])

  const retry = useCallback(() => setAttempt(a => a + 1), [])
  return { health, phase, elapsed, retry }
}

import { useCallback, useEffect, useState } from 'react'
import type { DocSummary, ExtractionResult } from './types'

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
      const res = await fetch(`/api/documents/${id}`)
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

  const load = useCallback(() => {
    setError(null)
    fetch(`/api/documents?limit=${HISTORY_LIMIT}`)
      .then(r => r.json())
      .then(setDocs)
      .catch(() => setError('Could not reach the server.'))
  }, [])

  useEffect(load, [load])

  return { docs, setDocs, error, reload: load }
}

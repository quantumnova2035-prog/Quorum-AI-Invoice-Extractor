import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { BatchItem, DeskDoc, DocSummary, ExtractionResult, FieldResult } from './types'
import { Detail, reviewCount } from './ReviewUI'
import { useDocCache, useHistory, useIsMobile, useServerWake } from './hooks'
import { api } from './api'
import DocStack from './components/DocStack'
import Home from './components/Home'
import MobileNav, { type View } from './components/MobileNav'
import Rail from './components/Rail'
import Settings from './components/Settings'
import UploadView from './components/UploadView'
import { FieldTools, NoFieldsMatch, filterFields, type FieldFilter } from './components/FieldTools'
import { IconDoc } from './components/Icons'
import { ByoDialog } from './components/ByoKeys'
import { byoActive, byoHeaders, loadByo, saveByo, type ByoSettings } from './byok'
import { Waking } from './components/Waking'

/* Two layouts over one state model.

   Desktop is a workspace: a stack of documents across the top, the ones you
   have open as closeable tabs down the left, and the extracted data filling the
   rest. Several documents open at once, because reconciling one invoice against
   another is the actual job.

   Mobile is three destinations behind a floating nav: Home (everything you have
   ever processed), Upload (drop files, watch them land), Settings. A phone has
   no room for a stack and a rail and a detail pane, and shrinking all three
   gives you three unusable things instead of one good one. */

const MAX_CONCURRENT = 3 // keep free-tier rate limits happy; see backend/.env
const uid = () => Math.random().toString(36).slice(2, 10)

export default function App() {
  const isMobile = useIsMobile()
  const [view, setView] = useState<View>('home')
  const { health, phase: wakePhase, elapsed: wakeMs, retry: retryWake } = useServerWake()

  const [batch, setBatch] = useState<BatchItem[]>([])
  const [corrections, setCorrections] = useState<Record<string, Record<string, string>>>({})
  const startedIds = useRef<Set<string>>(new Set())

  const { docs, setDocs, error: histError, reload } = useHistory()
  const { cache, loading, error: docError, ensure, drop } = useDocCache()

  const [openTabs, setOpenTabs] = useState<DeskDoc[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [fieldQ, setFieldQ] = useState('')
  const [fieldFilter, setFieldFilter] = useState<FieldFilter>('all')
  /* Mobile only. Opening a document from Home used to switch to the Upload tab,
     which meant tapping any past invoice hid the upload box entirely - there was
     then no way to add a file without first noticing you had to tap Upload
     again. A document is its own screen, pushed over the nav destination you
     came from, with a back button. */
  const [docOpen, setDocOpen] = useState(false)

  /* Bring-your-own-key. Read once from localStorage on mount rather than on
     every render, and written back on every change so a reload keeps it. */
  const [byo, setByoState] = useState<ByoSettings>(loadByo)
  const [byoOpen, setByoOpen] = useState(false)
  const setByo = useCallback((v: ByoSettings) => { setByoState(v); saveByo(v) }, [])
  const byoOn = byoActive(byo)

  /* The upload worker is a long-lived effect; reading the setting through a
     ref keeps it current without making every keystroke in the key field
     restart the queue. */
  const byoRef = useRef(byo)
  byoRef.current = byo

  const enqueue = useCallback((files: FileList | File[]) => {
    const items: BatchItem[] = Array.from(files).map(file => ({ id: uid(), file, status: 'queued' }))
    if (!items.length) return
    setBatch(prev => [...prev, ...items])
    setActiveId(items[0].id)
    if (isMobile) { setDocOpen(false); setView('upload') }
  }, [isMobile])

  // Worker pool: whenever the queue changes, top up to MAX_CONCURRENT uploads in
  // flight. `startedIds` guards against React's double-invoke in dev mode (and
  // against this effect re-firing mid-upload) starting the same file twice.
  useEffect(() => {
    const processing = batch.filter(b => b.status === 'processing').length
    const queued = batch.filter(b => b.status === 'queued' && !startedIds.current.has(b.id))
    const toStart = queued.slice(0, Math.max(0, MAX_CONCURRENT - processing))
    if (!toStart.length) return

    const ids = toStart.map(b => b.id)
    ids.forEach(id => startedIds.current.add(id))
    setBatch(prev => prev.map(b => (ids.includes(b.id) ? { ...b, status: 'processing' } : b)))

    for (const item of toStart) {
      (async () => {
        try {
          const body = new FormData()
          body.append('file', item.file)
          /* Read at send time, not captured when the upload was queued - a
             key pasted while a batch is in flight should apply to the files
             that have not gone yet. */
          const res = await fetch(api('/api/extract'),
                                  { method: 'POST', body, headers: byoHeaders(byoRef.current) })
          if (!res.ok) {
            const detail = await res.json().catch(() => null)
            throw new Error(detail?.detail ?? `HTTP ${res.status}`)
          }
          const result: ExtractionResult = await res.json()
          setBatch(prev => prev.map(b => (b.id === item.id ? { ...b, status: 'done', result } : b)))
          // A finished upload is now a history record too; refresh so Home and
          // the stack agree about what exists.
          reload()
        } catch (e) {
          setBatch(prev => prev.map(b => (b.id === item.id
            ? { ...b, status: 'error', error: e instanceof Error ? e.message : String(e) }
            : b)))
        }
      })()
    }
  }, [batch, reload])

  const saveCorrection = useCallback(async (docId: string | undefined, f: FieldResult, value: string) => {
    if (!docId) return
    setCorrections(prev => ({ ...prev, [docId]: { ...(prev[docId] ?? {}), [f.name]: value } }))
    await fetch(api('/api/corrections'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        document_id: docId,
        field_name: f.name,
        original_value: f.value === null ? null : String(f.value),
        corrected_value: value,
        original_confidence: f.confidence,
      }),
    }).catch(() => { /* a failed save must not lose the user's edit */ })
  }, [])

  /* The stack is this session's uploads first (newest work, still warm), then
     everything already in the database that is not a duplicate of one of them. */
  const stack: DeskDoc[] = useMemo(() => {
    const live: DeskDoc[] = batch.map(b => ({
      id: b.id,
      filename: b.file.name,
      status: b.status,
      origin: 'batch',
      docId: b.result?.document_id ?? null,
      result: b.result,
      error: b.error,
    }))
    const liveDocIds = new Set(live.map(l => l.docId).filter(Boolean))
    const past: DeskDoc[] = (docs ?? [])
      .filter(d => !liveDocIds.has(d.id))
      .map(d => ({
        id: d.id,
        filename: d.filename,
        status: 'done' as const,
        origin: 'history' as const,
        docId: d.id,
        createdAt: d.created_at,
      }))
    return [...live, ...past]
  }, [batch, docs])

  const openDoc = useCallback((d: DeskDoc) => {
    setOpenTabs(prev => (prev.some(t => t.id === d.id) ? prev : [...prev, d]))
    setActiveId(d.id)
    if (d.origin === 'history' && d.docId) ensure(d.docId)
  }, [ensure])

  const closeTab = useCallback((id: string) => {
    setOpenTabs(prev => {
      const idx = prev.findIndex(t => t.id === id)
      const next = prev.filter(t => t.id !== id)
      // Closing the tab you are looking at should land on a neighbour, not on
      // an empty canvas - the workspace stays where you were.
      setActiveId(cur => {
        if (cur !== id) return cur
        return next[Math.min(idx, next.length - 1)]?.id ?? null
      })
      return next
    })
  }, [])

  const openFromHistory = useCallback((d: DocSummary) => {
    openDoc({
      id: d.id, filename: d.filename, status: 'done',
      origin: 'history', docId: d.id, createdAt: d.created_at,
    })
    if (isMobile) setDocOpen(true)
  }, [openDoc, isMobile])

  // Any nav tap leaves the document screen - the nav is the way out of it.
  const goTo = useCallback((v: View) => { setDocOpen(false); setView(v) }, [])

  const doDelete = useCallback(async (id: string) => {
    setDeletingId(id)
    try {
      const res = await fetch(api(`/api/documents/${id}`), { method: 'DELETE' })
      if (!res.ok) {
        const d = await res.json().catch(() => null)
        throw new Error(d?.detail ?? `HTTP ${res.status}`)
      }
      setDocs(prev => prev?.filter(d => d.id !== id) ?? null)
      closeTab(id)
      drop(id)
    } catch {
      reload()
    } finally {
      setDeletingId(null)
    }
  }, [setDocs, closeTab, drop, reload])

  /* Whatever the canvas should show right now, resolved from whichever source
     the active document came from. */
  const activeTab = openTabs.find(t => t.id === activeId) ?? null
  const liveResult = batch.find(b => b.id === activeId)?.result
  const activeResult: ExtractionResult | undefined =
    liveResult ?? (activeTab?.docId ? cache[activeTab.docId] : undefined)
  const activeBatchItem = batch.find(b => b.id === activeId)

  const shownFields = useMemo(
    () => (activeResult ? filterFields(activeResult.fields, fieldQ, fieldFilter) : []),
    [activeResult, fieldQ, fieldFilter])

  const totalNeedingReview = batch
    .filter(b => b.status === 'done')
    .reduce((s, b) => s + (b.result ? reviewCount(b.result) : 0), 0)

  /* One honest summary of whether the app can actually do its job right now.
     Naming the specific failure matters: "no database" and "no LLM key" need
     completely different fixes. */
  const waking = wakePhase === 'waking'
  const wakeFailed = wakePhase === 'failed'
  const healthOk = !!health && health.llm_providers.length > 0 && health.supabase.enabled
  const healthTone = healthOk ? 'ok' : 'bad'
  /* "No LLM key" while the server is still booting is a lie that reads as a
     misconfigured app rather than a sleeping one, so waking is its own state
     rather than a fallback to the worst case. */
  const healthText = waking ? 'Waking…'
    : wakeFailed ? 'Unreachable'
    : !health ? 'Checking…'
    : !health.llm_providers.length ? 'No LLM key'
    : !health.supabase.enabled ? 'Not saving'
    : 'Ready'

  const header = (
    <header className="topbar">
      <div className="brand">
        <span className="mark"><IconDoc size={17} /></span>
        <div>
          <h1>Quorum AI</h1>
          <div className="sub">Invoice extractor · confidence-scored, field by field</div>
        </div>
      </div>
      <span className="spacer" />
      {(health || waking || wakeFailed) && isMobile && (
        /* Two bare dots told you nothing - a green dot is not a status, it is a
           decoration. One chip that names the state, and taps through to
           Settings where the full provider chain already lives. */
        <button className={`pill statusbtn ${waking ? 'waking' : healthTone}`}
                onClick={() => goTo('settings')}>
          <i className={`dot ${waking ? 'wake' : healthTone === 'ok' ? 'ok' : 'off'}`} />
          <span className="t">{healthText}</span>
        </button>
      )}
      {(waking || wakeFailed) && !isMobile && (
        <div className="health">
          <span className={`pill statusbtn ${waking ? 'waking' : 'bad'}`} style={{ cursor: 'default' }}>
            <i className={`dot ${waking ? 'wake' : 'off'}`} />
            <span className="t">{healthText}</span>
            {waking && <span className="more mono">{Math.floor(wakeMs / 1000)}s</span>}
          </span>
        </div>
      )}
      {health && !isMobile && (
        <div className="health">
          <span className="pill">
            <i className={`dot ${health.supabase.enabled ? 'ok' : 'off'}`} />
            <span className="t">{health.supabase.enabled ? 'Supabase' : 'No database'}</span>
          </span>
          {/* The provider chip is the way into key settings on desktop: it is
              already the thing that names which model answers, so it is where
              someone looks to change it. */}
          <button
            className={`pill mono providerbtn${byoOn ? ' byo' : ''}`}
            onClick={() => setByoOpen(true)}
            title={byoOn ? `Your key · ${byo.model}` : health.llm_providers.join(' → ')}
          >
            <i className={`dot ${byoOn || health.llm_providers.length ? 'ok' : 'off'}`} />
            {/* A bare text node inside a flex container becomes an anonymous
                flex item, which cannot be given overflow/text-overflow - so the
                label needs a real element to truncate against. */}
            <span className="t">
              {byoOn ? byo.model.split('/').pop() : (health.llm_providers[0] ?? 'no LLM key')}
            </span>
            {byoOn
              ? <span className="more">your key</span>
              : health.llm_providers.length > 1 &&
                  <span className="more">+{health.llm_providers.length - 1}</span>}
          </button>
        </div>
      )}
    </header>
  )

  const wakeBanner = (waking || wakeFailed) && (
    <Waking elapsed={wakeMs} failed={wakeFailed} onRetry={retryWake} />
  )

  const noProvider = health && !health.llm_providers.length && !byoOn && (
    <div className="warn" style={{ margin: '12px 18px 0' }}>
      No LLM provider is configured. Add <code>OPENROUTER_API_KEY</code> to{' '}
      <code>backend/.env</code> and restart the backend.
    </div>
  )

  /* ------------------------------------------------------------- mobile --- */

  if (isMobile) {
    return (
      <div className="app">
        {header}
        {wakeBanner}
        {noProvider}
        <div className="workspace">
          <div className="canvas">
            <div className="canvas-body">
              {docOpen && (
                <>
                  <button className="backbtn" onClick={() => setDocOpen(false)}>
                    <span aria-hidden>←</span> All documents
                  </button>
                  {activeResult ? (
                    <>
                      <FieldTools q={fieldQ} filter={fieldFilter} onQ={setFieldQ}
                                  onFilter={setFieldFilter} />
                      <Detail result={activeResult}
                              corrected={corrections[activeResult.document_id ?? ''] ?? {}}
                              onSave={saveCorrection} fields={shownFields} />
                      {shownFields.length === 0 &&
                        <NoFieldsMatch filter={fieldFilter} q={fieldQ} />}
                    </>
                  ) : <p className="muted"><span className="spinner" />Loading document…</p>}
                </>
              )}

              {!docOpen && view === 'home' && (
                docs === null
                  ? <p className="muted"><span className="spinner" />Loading…</p>
                  : histError
                    ? <div className="err">{histError}</div>
                    : <Home docs={docs} activeId={activeId} onOpen={openFromHistory}
                            onDelete={doDelete} deletingId={deletingId} />
              )}

              {!docOpen && view === 'upload' && (
                <UploadView batch={batch} activeId={activeId} corrections={corrections}
                            onFiles={enqueue} onSelect={setActiveId} onSave={saveCorrection}
                            fieldQ={fieldQ} fieldFilter={fieldFilter}
                            onFieldQ={setFieldQ} onFieldFilter={setFieldFilter} />
              )}

              {!docOpen && view === 'settings' &&
              <Settings health={health} byo={byo} onByo={setByo} />}

              {docError && <div className="err" style={{ marginTop: 12 }}>{docError}</div>}
            </div>
          </div>
        </div>
        <MobileNav view={view} onChange={goTo} badge={totalNeedingReview} />
      </div>
    )
  }

  /* ------------------------------------------------------------ desktop --- */

  return (
    <div className="app">
      {header}
      {wakeBanner}
      {noProvider}

      <ByoDialog open={byoOpen} onClose={() => setByoOpen(false)}
                 value={byo} onChange={setByo} />

      <DocStack docs={stack} activeId={activeId} onOpen={openDoc} onFiles={enqueue} />

      <div className={`workspace ${collapsed ? 'collapsed' : ''}`}>
        <Rail tabs={openTabs} activeId={activeId} collapsed={collapsed}
              onSelect={setActiveId} onClose={closeTab}
              onToggle={() => setCollapsed(c => !c)} />

        <main className="canvas">
          {collapsed && (
            <button className="rail-peek iconbtn" onClick={() => setCollapsed(false)}
                    aria-label="Show open documents" title="Show open documents">
              <IconDoc size={15} />
            </button>
          )}

          {activeResult && (
            <FieldTools q={fieldQ} filter={fieldFilter} onQ={setFieldQ}
                        onFilter={setFieldFilter} className="canvas-tools" />
          )}

          <div className="canvas-body">
            {!activeId && (
              <div className="empty-state">
                <span className="ico"><IconDoc size={22} /></span>
                <h3>Nothing open</h3>
                <p>
                  Pick a document from the stack above to open it here. Open as many as you
                  need — each one becomes a tab on the left, and closing a tab does not
                  delete anything.
                </p>
              </div>
            )}

            {activeBatchItem?.status === 'queued' && <p className="muted">Waiting in the queue…</p>}
            {activeBatchItem?.status === 'processing' && (
              <p className="muted"><span className="spinner" />Extracting {activeBatchItem.file.name}…</p>
            )}
            {activeBatchItem?.status === 'error' && (
              <div className="err">
                <strong>Extraction failed for {activeBatchItem.file.name}.</strong>{' '}
                {activeBatchItem.error}
              </div>
            )}

            {activeTab?.origin === 'history' && !activeResult && loading && (
              <p className="muted"><span className="spinner" />Loading document…</p>
            )}

            {activeResult && (
              <>
                <Detail result={activeResult}
                        corrected={corrections[activeResult.document_id ?? ''] ?? {}}
                        onSave={saveCorrection}
                        fields={shownFields} />
                {shownFields.length === 0 && <NoFieldsMatch filter={fieldFilter} q={fieldQ} />}
              </>
            )}

            {docError && <div className="err" style={{ marginTop: 12 }}>{docError}</div>}
          </div>
        </main>
      </div>
    </div>
  )
}

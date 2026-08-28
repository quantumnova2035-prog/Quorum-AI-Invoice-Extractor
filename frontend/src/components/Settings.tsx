import type { Health } from '../types'

/* The three items here are on the roadmap, not shipped (FUTURE-UPDATES.md §3,
   §4, §5). They are rendered as disabled previews rather than working-looking
   controls: a key field that silently does nothing is worse than no field, and
   on a project whose whole point is honest reporting it would be the wrong kind
   of lie to tell in its own settings screen. */

type Row = {
  section: string
  title: string
  blurb: string
  status: 'planned' | 'blocked'
  note?: string
}

const ROADMAP: Row[] = [
  {
    section: '§3',
    title: 'Bring your own API keys',
    blurb: 'Paste a key for OpenRouter, Groq, Google or any other provider and use '
         + 'your own quota instead of the one baked into the server.',
    status: 'planned',
    note: 'Blocked on one real decision: where a user-supplied key is allowed to live. '
        + 'Browser storage means it survives a refresh but is readable by any script on '
        + 'the page; server-side means it has to be encrypted at rest and scoped to a '
        + 'session. That is a security call, not a UI one.',
  },
  {
    section: '§4',
    title: 'Local model, no key at all',
    blurb: 'Point the extractor at Ollama or LM Studio on this machine. Nothing leaves '
         + 'the computer and nothing is billed.',
    status: 'planned',
    note: 'The router already speaks the OpenAI-compatible format Ollama serves, so this '
        + 'is mostly configuration. The open question is accuracy: it needs its own eval '
        + 'run before the number can be published, and most small local models cannot '
        + 'read scans or photos at all.',
  },
  {
    section: '§5',
    title: 'Themes',
    blurb: 'Switch the whole interface between colour schemes, remembered between visits '
         + 'and following the system light/dark setting by default.',
    status: 'blocked',
    note: 'The groundwork is done - every colour, blur, shadow and easing in this build is '
        + 'a custom property in one block, so a theme is a new block of values rather than '
        + 'a second stylesheet. Waiting on your reference examples before any palette is '
        + 'guessed.',
  },
]

export default function Settings({ health }: { health: Health | null }) {
  return (
    <>
      <div className="section-title">Active configuration</div>

      {health ? (
        <div className="summary">
          <div className="stat">
            <div className="k">Extraction passes</div>
            <div className="v">{health.passes}</div>
          </div>
          <div className="stat">
            <div className="k">Auto-accept at</div>
            <div className="v">{health.thresholds.auto_accept}</div>
          </div>
          <div className="stat">
            <div className="k">Review at</div>
            <div className="v">{health.thresholds.review}</div>
          </div>
          <div className="stat">
            <div className="k">Database</div>
            <div className={`v ${health.supabase.enabled ? 'green' : 'amber'}`}
                 style={{ fontSize: 15 }}>
              {health.supabase.enabled ? 'Supabase connected' : 'Not configured'}
            </div>
          </div>
        </div>
      ) : (
        <p className="muted" style={{ marginBottom: 18 }}>
          <span className="spinner" />Reading server configuration…
        </p>
      )}

      {health && (
        <>
          <div className="section-title">Provider chain</div>
          <p className="muted" style={{ fontSize: 13, marginBottom: 10, lineHeight: 1.55 }}>
            Tried in order. If one refuses or rate-limits, the next takes over — which is
            why a document can come back priced by a provider you did not expect.
          </p>
          <div className="doclist" style={{ marginBottom: 4 }}>
            {health.llm_providers.length === 0 && (
              <div className="warn">
                No provider is configured. Add <code>OPENROUTER_API_KEY</code> to{' '}
                <code>backend/.env</code> and restart the backend.
              </div>
            )}
            {health.llm_providers.map((p, i) => (
              <div className="docrow" key={p} style={{ animationDelay: `${i * 35}ms` }}>
                <span className="badge blue">{i + 1}</span>
                <div className="docrow-main" style={{ cursor: 'default' }}>
                  <span className="docrow-name">{p}</span>
                  <span className="docrow-meta">
                    {i === 0 ? 'primary' : `fallback ${i}`}
                  </span>
                </div>
              </div>
            ))}
          </div>

          <p className="muted" style={{ fontSize: 12.5, marginTop: 10, lineHeight: 1.55 }}>
            Weights — self-reported {health.weights.self_reported}, cross-pass agreement{' '}
            {health.weights.agreement}, rule validation {health.weights.rules}. These come
            from <code>backend/.env</code> and are read at startup.
          </p>
        </>
      )}

      <div className="section-title">On the roadmap</div>

      <div className="doclist">
        {ROADMAP.map((r, i) => (
          <div key={r.section} className="roadmap" style={{ animationDelay: `${i * 40}ms` }}>
            <div className="roadmap-top">
              <span className="badge blue">{r.section}</span>
              <span className="roadmap-title">{r.title}</span>
              <span className={`badge ${r.status === 'blocked' ? 'amber' : 'green'}`}>
                {r.status === 'blocked' ? 'waiting on you' : 'planned'}
              </span>
            </div>
            <p className="roadmap-blurb">{r.blurb}</p>
            {r.note && <p className="roadmap-note">{r.note}</p>}
          </div>
        ))}
      </div>

      <p className="muted" style={{ fontSize: 12.5, marginTop: 16, lineHeight: 1.55 }}>
        Nothing on this screen is a working control yet. It is here so the shape of the
        settings surface exists before the features land, not to imply they already work.
      </p>
    </>
  )
}

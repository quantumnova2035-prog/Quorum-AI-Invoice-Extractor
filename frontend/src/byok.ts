/* Bring-your-own-key.

   The key lives in this browser's localStorage and is sent as a header with
   each extraction. It is never written to our database and never logged - the
   server redacts it out of error text the same way it redacts its own keys.

   What this cannot claim, and so does not: the key passes THROUGH the server on
   its way to OpenRouter. A browser cannot call OpenRouter directly without
   exposing the key to every site the user visits via CORS, so a proxy is the
   only safe shape - but it does mean the server handles the value in memory for
   the length of one request. The UI says so rather than implying otherwise. */

export interface ByoModel {
  id: string
  label: string
  /** USD per 1M tokens. null = free. */
  input: number | null
  output: number | null
  context: string
  released: string
}

/* Prices as published by OpenRouter and supplied for this build - they are
   shown to help someone choose, not to compute a bill. Actual cost is always
   whatever OpenRouter reports for the request itself, which is what the app
   records, so a stale entry here can never turn into a wrong number in the
   ledger. Verify at https://openrouter.ai/models before relying on them. */
export const BYO_MODELS: ByoModel[] = [
  { id: 'nvidia/nemotron-3-ultra-550b-a55b:free', label: 'Nemotron 3 Ultra 550B',
    input: null, output: null, context: '1M', released: 'Jun 2026' },
  { id: 'openai/gpt-oss-120b', label: 'GPT-OSS 120B',
    input: 0.03, output: 0.17, context: '131K', released: 'Aug 2025' },
  { id: 'deepseek/deepseek-v4-flash-0731', label: 'DeepSeek V4 Flash',
    input: 0.05, output: 0.16, context: '1M', released: 'Jul 2026' },
  { id: 'z-ai/glm-5.3-flash', label: 'GLM 5.3 Flash',
    input: 0.075, output: 0.25, context: '1M', released: 'Aug 2026' },
  { id: 'openai/gpt-5.6-luna', label: 'GPT-5.6 Luna',
    input: 0.20, output: 1.20, context: '1M', released: 'Jul 2026' },
  { id: 'google/gemini-3-flash-preview', label: 'Gemini 3 Flash (preview)',
    input: 0.50, output: 3.00, context: '1M', released: 'Dec 2025' },
  { id: 'google/gemini-3.6-flash', label: 'Gemini 3.6 Flash',
    input: 0.75, output: 3.75, context: '1M', released: 'Jul 2026' },
  { id: 'google/gemini-3.7-flash', label: 'Gemini 3.7 Flash',
    input: 0.75, output: 3.75, context: '1M', released: 'Aug 2026' },
  { id: 'anthropic/claude-haiku-4.5', label: 'Claude Haiku 4.5',
    input: 1.00, output: 5.00, context: '200K', released: 'Oct 2025' },
  { id: 'anthropic/claude-sonnet-5', label: 'Claude Sonnet 5',
    input: 2.00, output: 10.00, context: '1M', released: 'Jun 2026' },
  { id: 'anthropic/claude-opus-5', label: 'Claude Opus 5',
    input: 5.00, output: 25.00, context: '1M', released: 'Jul 2026' },
]

export interface ByoSettings {
  enabled: boolean
  key: string
  model: string
}

export const BYO_DEFAULT: ByoSettings = {
  enabled: false,
  key: '',
  model: BYO_MODELS[1].id,   // the cheapest priced model, not the free one
}

const STORAGE = 'quorum.byok'

export function loadByo(): ByoSettings {
  try {
    const raw = localStorage.getItem(STORAGE)
    if (!raw) return BYO_DEFAULT
    const v = JSON.parse(raw) as Partial<ByoSettings>
    return {
      enabled: !!v.enabled,
      key: typeof v.key === 'string' ? v.key : '',
      model: typeof v.model === 'string' && v.model ? v.model : BYO_DEFAULT.model,
    }
  } catch {
    // A private window, blocked site data, or hand-edited JSON. Falling back to
    // the server's own keys is always safe, so none of these need reporting.
    return BYO_DEFAULT
  }
}

export function saveByo(v: ByoSettings): void {
  try { localStorage.setItem(STORAGE, JSON.stringify(v)) } catch { /* not fatal */ }
}

/** Only actually usable when it is on AND has both halves. */
export function byoActive(v: ByoSettings): boolean {
  return v.enabled && v.key.trim().length > 0 && v.model.trim().length > 0
}

/** Headers for /api/extract. Empty object when the server's own keys apply. */
export function byoHeaders(v: ByoSettings): Record<string, string> {
  return byoActive(v)
    ? { 'X-LLM-Key': v.key.trim(), 'X-LLM-Model': v.model.trim() }
    : {}
}

export function priceLabel(m: ByoModel): string {
  if (m.input === null) return 'Free'
  const f = (n: number) => (n < 1 ? `$${n}` : `$${n.toFixed(2).replace(/\.00$/, '')}`)
  return `${f(m.input)} / ${f(m.output ?? m.input)}`
}

/** Enough of the key to recognise, never enough to use. */
export function maskKey(k: string): string {
  const s = k.trim()
  if (s.length <= 10) return '•'.repeat(Math.max(s.length, 4))
  return `${s.slice(0, 6)}…${s.slice(-4)}`
}

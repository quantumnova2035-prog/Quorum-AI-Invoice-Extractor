# Future updates — Quorum AI

Running backlog. Nothing here is started unless its checkbox says so.
Ordered roughly by "do this first", but the sections are independent — we can
pick any one and finish it end to end.

Status key: `[ ]` not started · `[~]` in progress · `[x]` done

---

## 0. Blocked / waiting

- [ ] **Re-run the full 60-invoice evaluation.** Free-tier LLM quotas were
      exhausted on 2026-08-26 by the volume of testing done that day. The
      README currently publishes a real but partial result (34 documents:
      93.3% field accuracy, 90.6% auto-approved, 0% escaped errors). Once
      quotas reset, one command finishes it:
      ```
      backend/.venv/Scripts/python.exe scripts/evaluate.py --dir data/synthetic --limit 60 --tune
      ```
      Narendran will say when to run this — do not run it unprompted.

---

## 1. Cost tracking (per document, per provider) — DONE (2026-08-27)

**Technically possible: yes.** Every OpenAI-compatible provider returns a
`usage` block (`prompt_tokens`, `completion_tokens`) alongside the completion.
OpenRouter additionally returns a real charged **`cost` in USD** when the
request body includes `"usage": {"include": true}` — this is exactly how the
accidental $0.117 spend on `openai/gpt-oss-20b` was caught. Gemini returns
`usageMetadata` with token counts instead of a cost, so its cost is computed
locally from a small per-model price table.

### Work items
- [x] Return usage from the router, on the `LLMCall` object added in §2.
- [x] Send `"usage": {"include": true}` on OpenRouter requests so the real
      charged cost comes back rather than being estimated.
- [x] Add a fallback price table (`config.MODEL_PRICING`) for providers that
      report tokens but not cost. Estimated costs are marked with `*` in the UI
      and never presented as billed figures.
- [x] Sum across passes, including retries and failed-provider attempts.
- [x] Persist per-document cost, tokens, and the estimated/known flags.
- [x] Display: a `Cost` stat card, plus per-pass tokens and cost in the same
      expandable panel as the timing breakdown.
- [x] Display: running total for the current batch.
- [x] Show `$0` as **"free tier"** rather than a bare zero.
- [x] Totals strip on the History tab (documents, mean auto-accept, total time,
      total cost). Labelled "last 100" whenever the list is capped, and the
      count of unpriced documents is shown next to the total so it reads as a
      floor rather than a complete figure.

### What shipped
- `_read_usage()` in the router handles both response shapes and returns
  `(prompt_tokens, completion_tokens, cost_usd, is_estimated)`.
- `schemas.Cost` on `ExtractionResult`, persisted to new `documents.cost`
  (jsonb) and `documents.cost_usd` columns.
- A warning on any document that cost more than $0, naming the likely cause —
  the check that would have caught the `gpt-oss-20b` surprise the same day
  rather than weeks later.

### The distinction the whole design turns on
**Free, unknown, and priced are three different states.** A provider that
reports no price leaves `cost_usd` as `None`, the document as
`known: false`, and the UI as "partly unknown" with `n/r` on the offending
pass — never `$0`. Collapsing unknown into zero is exactly how a paid model
passes for free, which already happened once on this project.

`MODEL_PRICING` therefore ships **empty**. A stale hardcoded price table looks
authoritative while being wrong, which is worse than admitting ignorance. Set
`MODEL_PRICING_USD_PER_MTOK` in `.env` to opt into estimates:

    MODEL_PRICING_USD_PER_MTOK=gemini-3.5-flash:0.30/2.50,llama-3.3-70b-versatile:0.59/0.79

### Gemini gotcha (found by checking the live response, not the docs)
`usageMetadata.candidatesTokenCount` **excludes** `thoughtsTokenCount`, but
reasoning tokens are billed as output. A live call returned 3 prompt / 10
candidates / 127 thoughts — so counting only `candidates` would have
understated the billable output by more than 10x. The router adds both.

### Measured on a real document (2026-08-27)
`invoice_003.pdf`: 1,764 tokens in, **7,522 out**, $0 reported, 44.7s.
The output count is the notable part — `nemotron-3-super` is a reasoning model
and spends most of its output budget thinking. It is free today, so this costs
nothing; on a paid per-output-token model the same workload would be dominated
by tokens nobody ever sees. Worth remembering before swapping in a paid model
on output-heavy work.

### Note on precision
Per-document costs on free models are `0`, and on cheap models are ~$0.0002,
so two decimal places would render every invoice as "$0.00". `usd()` in the UI
keeps four decimals below a cent and rounds to cents only above it.

---

## 2. Processing time tracking — DONE (2026-08-27)

**Technically possible: yes**, and simpler than cost — it is pure local
measurement, no provider cooperation needed.

### Work items
- [x] Time each LLM call in the router (`time.perf_counter()` around the
      `client.post`), returned as `latency_ms` on the `LLMCall` above.
- [x] Time the whole pipeline per document in `extraction.extract()`, split
      into meaningful phases so a slow document is *diagnosable*, not just
      slow:
      - parse / text extraction (PyMuPDF, or image encoding for scans)
      - LLM pass 1
      - LLM pass 2
      - confidence scoring (will be ~0ms, but proves it is not the bottleneck)
      - database write
- [x] Record **wall-clock total** separately from the sum of the phases. The
      two passes may run concurrently, so summing them overstates the real
      elapsed time — showing both makes the concurrency visible.
- [x] Persist per-document total + phase breakdown.
- [x] Display: a `Took` stat card (e.g. `4.2s`), with the phase breakdown in
      an expandable panel (the cost breakdown will join it in §1).
- [x] Display: on the batch view, average and slowest document, so a
      40-invoice run has an honest throughput number.
- [x] Show retry/backoff time distinctly. A document that waited 3s on a 429
      backoff was not "slow to extract" — it was rate-limited, and that is a
      completely different problem to fix.

### What shipped
- `llm_router.LLMCall` replaces the old `(json, provider)` tuple and carries
  `latency_ms`, `wasted_ms`, `attempts`, plus `prompt_tokens` /
  `completion_tokens` / `cost_usd` left as `None` for §1 to fill in.
- `schemas.Timing` / `schemas.CallTiming`, exposed on `ExtractionResult` and
  persisted to the new `documents.timing` (jsonb) and `documents.total_ms`
  columns.
- `TimingPanel` in the UI: phase strip, per-pass table, and two plain-English
  notes — one stating what the concurrency actually bought, one separating
  rate-limit waiting from extraction time.

### Requires a database migration
`backend/supabase_schema.sql` gained `timing` and `total_ms`. Until it is
re-run in the Supabase SQL editor, extractions still save correctly but the
timing is dropped and a warning says so on the document. The `alter table
... add column if not exists` lines at the top make it safe to re-run.

### Measured on a real document (2026-08-27)
`invoice_002.pdf`: 27.3s total — 8ms parse, 27.0s LLM, 0.3ms scoring, 358ms
save. The two passes took 26.6s and 19.9s individually but finished in 27.0s
wall clock, so the concurrency is real and now visible. Confidence scoring
being 0.3ms confirms the LLM is the entire cost, which is what the phase
split exists to prove.

### Gotcha found while building this
`wasted_ms` was first derived as "total elapsed minus the successful call",
which folded HTTP-client setup into it and reported ~350ms of retry waste on
requests that never retried. It is now accumulated only from attempts that
actually failed. Worth remembering for §1: a derived-by-subtraction metric
will quietly absorb whatever else happens to be in the window.

---

## 3. Bring-your-own API keys — SHIPPED

Goal: a user pastes their own key for whichever provider they have, and it
works — rather than the keys living only in `backend/.env`.

**Shipped for OpenRouter.** The key lives in the browser's `localStorage` and
travels as an `X-LLM-Key` header on `/api/extract`, alongside `X-LLM-Model`.
Headers rather than query parameters, because a query string is written to
access logs and browser history verbatim and this is a credential.

Three decisions worth keeping:

- **No fallback.** With a user key present the router returns exactly one
  provider and no chain. Silently falling back to the server's keys would
  spend our quota on their request and record the model and cost of a call
  they did not choose. A wrong key gets a 401 they can see.
- **The key is threaded explicitly** (`ByoKey` through `extract` → `_one_pass`
  → `complete_json` → `_providers`) rather than parked in a module global or a
  context variable, so every function that can see the secret says so in its
  signature.
- **Redaction covers it** on the same path as the server's own keys. Verified:
  a canary key sent through the UI appears in neither the error response nor
  the server log.

What it deliberately does not claim: the key passes *through* the server to
reach OpenRouter. A browser cannot call OpenRouter directly without exposing
the key to every site via CORS, so a proxy is the only safe shape — and the UI
says so rather than implying the server never sees it.

Still open: Groq and Google keys (only OpenRouter is wired), and the model
price table in `frontend/src/byok.ts` is display-only guidance — recorded cost
is always the figure OpenRouter reports for the request itself.

### Work items
- [ ] Settings panel in the UI: one row per provider (OpenRouter, Groq,
      Google AI Studio, OpenAI, Anthropic, Together, DeepSeek, …), each with
      a key field, a model field, an enable toggle, and drag-to-reorder for
      fallback priority.
- [ ] "Test key" button per provider — one cheap call, reports success,
      the resolved model, and (once §1 lands) what that test cost.
- [ ] Show each provider's live status: working / rate-limited / bad key /
      not configured. Rate-limited is the common real state and currently
      surfaces only as a cryptic failure.
- [ ] **Decide and document where user keys live.** This is a real security
      decision, not a detail:
      - *Browser `localStorage`, sent per-request* — keys never touch the
        server disk; but they sit in the browser and travel on each call.
      - *Server-side, encrypted at rest* — needs real key management and
        turns the app into a credential store, with everything that implies.
      - For a portfolio project, browser-local is the honest, defensible
        choice — but say so explicitly in the UI so nobody is surprised.
- [ ] Never log or echo a user-supplied key. The existing `_redact()` in
      `llm_router.py` already strips keys from error text (added after a real
      leak of a Gemini key into terminal output) — extend it to cover any
      user-supplied key too, not just the three from `.env`.
- [ ] Keep `.env` working as the default/fallback so the app still runs with
      zero configuration.

### Hard-won rule to enforce in the UI
A model returning HTTP 200 does **not** mean it is free. Before trusting any
`:free`-looking model, verify `"pricing": {"prompt": "0", "completion": "0"}`
via `GET https://openrouter.ai/api/v1/models`. Bake this into the key-setup
flow: when a user adds an OpenRouter model, fetch its real pricing and show it
plainly — "this model costs $0.03/M input" — *before* they run a batch.

---

## 4. Local SLM support (no API key at all)

**Technically possible: yes**, and it drops in cleanly. Ollama, LM Studio, and
vLLM all expose an OpenAI-compatible `/v1/chat/completions` endpoint, which is
exactly the shape `llm_router.Provider` already speaks. It needs a base-URL
setting and permission to send no `Authorization` header.

### Work items
- [ ] Add `OLLAMA_BASE_URL` (default `http://localhost:11434/v1`) and allow a
      `Provider` with an empty API key to still count as `available`.
      Currently `Provider.available` is `bool(self.api_key)`, which would
      exclude a keyless local server.
- [ ] Auto-detect a running local server and offer it in the UI as
      "Local model detected — use it?"
- [ ] Let local be *primary* with cloud as fallback, or vice versa. Local
      primary removes the free-tier quota ceiling entirely, which after
      2026-08-26 is a genuinely attractive property.
- [ ] Mark local-model cost as `$0` **and** as local — free-because-local is
      different from free-tier-with-a-daily-cap, and the UI should not
      conflate them.
- [ ] Vision: most small local models are text-only. The router already routes
      scans past text-only providers via `supports_vision` — make sure a local
      model is registered in `TEXT_ONLY_MODELS` unless it genuinely handles
      images (e.g. `llava`, `qwen2-vl`).
- [ ] **Re-run the eval against the local model and publish that number
      separately.** A small local model will very likely score lower than the
      cloud chain. That is a legitimate, interesting tradeoff to document
      (privacy + no quotas vs accuracy) — but only if the number is real.
      Do not present the cloud accuracy figure as if it applied to local.

---

## 5. Theming

The whole visual identity already runs off CSS custom properties in one file
(`frontend/src/index.css`), so themes are mostly a matter of defining
alternate palettes — no component changes needed.

Current theme: **Ledger** — warm paper background, ruled lines, ink-brown
text, serif headings, monospace numerals, stamped rust-red accent.
Deliberately not the default dark-navy/blue-glow "AI dashboard" look.

### Work items
- [ ] Restructure the palette into `[data-theme="..."]` blocks, same variable
      names throughout, so a theme is purely a set of values.
- [ ] Theme switcher UI, persisted to `localStorage`.
- [ ] Respect `prefers-color-scheme` for the initial pick.
- [ ] Build the additional themes from Narendran's examples — **still to be
      supplied.** Do not guess these; wait for the references.
- [ ] Check contrast on every theme, especially the confidence colors
      (green/amber/red). These carry actual meaning here — if they stop being
      distinguishable, the product stops working, so this is a correctness
      issue and not a cosmetic one.

---

## 6. General UI/UX improvements — REBUILT (2026-08-28)

The Ledger theme is gone. The whole interface was rebuilt as the "Glass"
theme, with two real layouts rather than one shrunk to fit.

- [x] Replace the generic dark "AI slop" styling. (Ledger theme, since
      superseded — kept at `frontend/src/index.ledger.css.bak`.)
- [x] Fix the empty/ghost cell in the stat grid.
- [x] **Glass theme** — white + dark blue, translucent chrome over a soft
      gradient ground. Every colour, blur, shadow, radius, easing and
      duration is a custom property in one `:root` block, so §5 is now a
      matter of adding blocks of values rather than restyling components.
- [x] **Desktop workspace** — document stack across the top, open documents
      as closeable tabs in a collapsible rail, extracted data in the canvas
      with search and a Needs review / Auto-accepted filter.
- [x] **Mobile** — floating translucent nav with three destinations: Home
      (the old History, now the front door), Upload, Settings.
- [x] Tab rework — done as part of the above.
- [ ] Keyboard navigation for the review queue (`j`/`k` between documents,
      `Enter` to correct, `Tab` between flagged fields). This is the single
      biggest real-world speed win for someone processing 40 invoices, and it
      is what actually separates this from a demo.
- [ ] Bulk actions: approve-all-clear, export batch to CSV/Tally-ready format.
- [ ] Show the source document alongside the extracted fields, so a shaky
      field can be checked against the invoice without leaving the page.
      Arguably the highest-value missing feature — right now a reviewer has to
      open the PDF separately to verify anything, which undercuts the whole
      "only check the shaky fields" premise.
- [ ] Highlight *where* on the page a value came from (bounding boxes).
      Significant work; only worth it after the side-by-side view exists.
- [ ] Better empty states and a first-run walkthrough.
- [ ] Progress detail during processing — currently just a spinner; with §2
      it can show the live phase ("pass 2 of 2…").
- [x] Mobile layout pass - done as part of the rebuild.

### What shipped

- `frontend/src/index.css` - full rewrite. Old theme kept at
  `src/index.ledger.css.bak` until the new one has been lived with.
- New `src/components/`: `MobileNav`, `DocStack`, `Rail`, `Toolbar`, `Home`,
  `UploadView`, `Settings`, `Icons`.
- `src/hooks.ts` - `useIsMobile`, `useDocCache` (opened documents are cached
  for the session so re-selecting a tab is instant), `useHistory`.
- `History.tsx` deleted; it became `components/Home.tsx`.
- `Detail` gained an optional `fields` prop so the canvas can filter the field
  list. The summary stats above it deliberately keep counting the *whole*
  document - a filter changes what you are looking at, not what it scored.

### Craft decisions worth not undoing

- **Glass on top-level surfaces only.** Nav, dock, rail, canvas and topbar run
  `backdrop-filter`; controls inside them get the glass *look* with no second
  blur pass. Stacking translucency destroys legibility and costs a whole extra
  paint. Deviating from this is what makes glass UIs look muddy.
- **Sliding thumbs are measured, not calculated.** The mobile nav indicator and
  the segmented controls read real `offsetLeft`/`offsetWidth` in a layout
  effect. Labels differ in width, so any hardcoded per-slot maths drifts, and a
  pill sitting a few pixels off its label is felt without being named.
- **One indicator that moves, never two that cross-fade.** A cross-fade reads
  as one thing vanishing and another appearing, not as movement.
- **No `ease-in` anywhere.** It delays the first frame, which is exactly when
  the user is looking. Entrances use a strong `ease-out`.
- **Nothing enters from `scale(0)`.** Cards and chips start at `.94-.96` with
  opacity - nothing in the real world appears out of nothing.
- **Keyframes only for entrances that cannot be interrupted;** transitions for
  everything the user can hit mid-flight, because transitions retarget from the
  current value and keyframes restart from zero.
- **Hover effects are gated behind `@media (hover: hover) and (pointer: fine)`**
  so a tap on a phone does not leave an element stuck in a hover state.
- `prefers-reduced-motion`, `prefers-reduced-transparency` (frosts the glass and
  drops the blur) and `prefers-contrast` are all handled.

### Gotchas hit while building this

- A bare text node inside a flex container becomes an anonymous flex item, which
  cannot take `overflow`/`text-overflow`. The status pill labels needed a real
  `<span>` to truncate against.
- Two `flex: 1` siblings split free space evenly. The topbar had `flex: 1` on
  both the brand block and the spacer, which truncated the product name on a
  phone while leaving ~170px empty beside it. Only one of them should grow.
- Collapsing the rail animates `grid-template-columns`, which genuinely reflows.
  Accepted deliberately for an occasional action; everything else stays on
  `transform`/`opacity`.

### Still open

- [ ] The rail collapse is the one layout-animating transition in the build. If
      it ever feels heavy on a slow machine, that is why.
- [ ] Dark mode. The token structure supports it; no dark palette is defined
      yet, because that is §5 and it is waiting on reference examples.

---

## 7. Correctness / robustness backlog

- [ ] **Validate against real invoices, not synthetic ones.** The published
      accuracy comes from generated test data plus a handful of real files.
      The README already flags this honestly. Roughly 100 hand-labelled real
      invoices are needed before quoting the accuracy figure externally.
- [ ] Handle multi-page invoices explicitly (currently the text of all pages
      is concatenated).
- [ ] Handle multi-invoice PDFs (several invoices in one file).
- [ ] Duplicate detection — the same invoice number from the same vendor twice
      is a genuine AP problem worth catching, and is cheap to check once the
      documents are already in Supabase.
- [ ] Expand the smoke tests around the degenerate-pass detector and the
      list-vs-dict unwrap; both were real production bugs found by actual use,
      and both deserve permanent regression coverage.

---

## 8. Shipping

- [ ] Deploy. `render.yaml` exists but has never been tested.
- [ ] Demo GIF for the README.
- [ ] Live link (the project plan requires one for every project).

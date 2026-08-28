# Quorum AI — Invoice Extractor

Extracts structured data from supplier invoices **and tells you how sure it is about
every single field**, so a clerk reviews the three fields that are shaky instead of
re-reading all forty invoices.

---

## The problem

A mid-size company receives ~800 supplier invoices a month as PDFs, scans, and phone
photos. Two people type them into Tally or SAP by hand. Four minutes each, typos
included, and vendors call when payments slip.

"PDF in, JSON out" does not fix this. When the model gets a total wrong, nobody finds
out until the wrong amount has been paid. An extractor without a trustworthy
confidence signal just moves the error from a typist to a machine.

**So the product is not the extraction. It is the confidence score and the review
screen.**

```
Vendor name      Sundaram Steel Pvt Ltd     99%  auto-accept
Invoice date     2024-03-12                 99%  auto-accept
Total amount     124500.00                  45%  needs a human
                 └ subtotal + tax = 123500.00 but total says 124500.00 — off by 1000.00
GST number       33AABCS1429B1ZP            45%  needs a human
                 └ GSTIN format is right but the check digit fails
```

Two fields to check instead of a whole invoice.

---

## How the confidence score works

This is the part nobody explains, so here it is in full. Three independent signals:

| Signal | What it is | Weight |
|---|---|---|
| **Self-reported** | The model's own `confidence` per field | 0.30 |
| **Agreement** | Same document extracted twice at temp 0.3; do the answers match? | 0.30 |
| **Rules** | Deterministic validation — arithmetic, checksums, date parsing | 0.40 |

```
final = 0.30·self + 0.30·agreement + 0.40·rules
```

**Rules carry the most weight because they are the only signal that can be *certain*.**
If the line items don't sum to the total, something is wrong — no model opinion
required. A field that fails a hard rule is capped at 0.45 and can never be
auto-accepted, however confident the model sounded.

The rules actually implemented:

- `subtotal + tax == total` (1% tolerance) — the single strongest check
- line items sum to the subtotal, or to the total
- **GSTIN mod-36 check digit** — not just the regex. Catches the OCR digit swaps a
  format check waves straight through
- dates parse to real calendar dates; invoice dates in the future are suspicious
- tax as a share of total falls within a plausible GST band
- invoice number shape, currency code, name and address plausibility

Everything a model returns is normalized before scoring, because models return
`"Rs. 1,24,500.00/-"` and `"12/03/2024"` no matter how firmly the prompt asks
otherwise. Indian digit grouping, `(1,234.50)` for negatives, and the trailing `/-`
that is a currency suffix rather than a minus sign are all handled.

---

## Results

Tested on 34 synthetic invoices (374 field predictions) via free-tier models
(OpenRouter + Google AI Studio, two extraction passes each):

```
Field-level accuracy            93.3%
Auto-approved (no human)        90.6%
Sent to human review             9.4%
Errors caught by the filter    100.0%
ERRORS THAT SLIPPED PAST         0.0%   (0 of 374 fields)   <-- the number that matters
```

That last line is the one worth caring about. A confidence score is only useful if
it catches your *actual* mistakes; 95% accuracy with a leaky filter is worse than
90% accuracy that knows when to ask a human.

**That 0% didn't come free — it came from a real bug the eval caught.** An earlier
run let 4.2% of fields slip through at high confidence, and every single one was
the same failure: `invoice_date`/`due_date` with the day and month transposed
(`2026-08-03` returned instead of `2026-03-08`). Both readings are valid calendar
dates, so the "does this parse" rule saw nothing wrong and passed it through at
98–100% confidence. The fix, in `confidence.py`: when a date's day and month are
both ≤ 12, the order is inherently ambiguous from the value alone, so confidence
is capped at 0.55 and it's routed to a human instead of asserted with false
certainty. That single rule took escaped errors to zero.

The `--tune` flag sweeps the threshold so you can see the trade-off directly:

```
 thresh  auto-approved  escaped   review
   0.60          99.2%     5.9%     0.8%
   0.75          97.9%     4.5%     2.1%
   0.80          95.2%     4.5%     4.8%
   0.85          90.6%     0.0%     9.4%   <- current default
   0.90          79.7%     0.0%    20.3%
   0.95          64.2%     0.0%    35.8%
```

Below 0.85 the system trades safety for convenience — more gets auto-approved, but
real errors start leaking through. 0.85 is the first threshold where escaped
errors hit zero on this set; pushing higher only sends more correct fields to a
human for no additional safety.

### Why 34 and not the full 60 — a real free-tier limit, not a shortcut

OpenRouter caps `:free` models at **50 requests/day per model** unless the account
has purchased $10+ in credits (then it's 1000/day); Google AI Studio has its own
separate daily quota. A single 60-invoice run at two passes each is 120 requests —
before even counting the dozens of other calls made while building and debugging
this — so a full run genuinely exhausts multiple providers' free tiers in one
sitting. `llm_router.py` already spreads load across four independent quotas
(three OpenRouter models on different upstreams, plus Google) specifically to
survive this, and it still isn't enough headroom for one un-throttled full run in
a single dev session. This is worth knowing before quoting an evaluation number to
anyone: **for real volume, this needs either a paid OpenRouter balance ($10 lifts
the cap 20x) or the requests spread across the day**, not more free-tier
juggling. The 34-document run above is what got through before every configured
free provider hit its daily ceiling simultaneously.

> These numbers are from the synthetic set (clean text layer, four layouts,
> varied date formats and Indian digit grouping — see
> `scripts/generate_invoices.py`), not hand-labelled real invoices. Synthetic PDFs
> flatter the parser because the text layer is always clean; the confidence
> mechanics and the arithmetic/checksum rules transfer directly to real invoices,
> but the accuracy number itself should be re-run against ~100 real ones before
> quoting it externally. Re-running the full 60 (or more, on real invoices) is a
> one-command follow-up once quotas reset:
> `python scripts/evaluate.py --dir data/synthetic --limit 60 --tune`

### Known failure modes

- **Ambiguous DD/MM vs MM/DD dates.** When both day and month are ≤ 12 the order
  can't be recovered from the value alone (see above) — the system now flags these
  for review instead of guessing, but it genuinely cannot resolve them
  automatically. Only a second source (a PO date, a delivery date) or a human could.
- **Multi-page invoices with line items spanning pages** — only the first 15 pages
  are read, and items split across a page break can be double-counted.
- **Phone photos at steep angles** — handled via the vision path, but accuracy drops.
  No deskew/denoise preprocessing yet; that's the highest-value next improvement.
- **Handwritten annotations** are ignored entirely.
- **Multi-currency invoices** — a single `currency` field, so mixed-currency
  documents lose information.
- **Free-tier rate limits** — the router retries and falls back, but under sustained
  load a pass can fail. When only one of two passes succeeds the agreement signal is
  unavailable, and the system deliberately becomes *more* conservative rather than
  pretending to be sure.
- **Model IDs get retired without notice.** `gemini-2.0-flash-exp:free` and
  `gemini-2.0-flash-001` both 404'd mid-build even though they were current when
  written. If extraction starts failing, check the provider's live model list
  before assuming the API key is bad.
- **A `:free` suffix must be verified, not assumed.** `openai/gpt-oss-20b`
  responded successfully in testing and looked interchangeable with a free
  model, but was quietly billing $0.03/M input and $0.13/M output tokens the
  whole time. Confirm `"pricing": {"prompt": "0", "completion": "0"}` at
  `GET https://openrouter.ai/api/v1/models` before trusting a model ID here.
- **Free-tier daily quotas are real and shared across a whole dev session.**
  OpenRouter caps `:free` models at ~50 requests/day each without a $10+
  account balance; Google AI Studio has its own separate daily cap. A single
  60-invoice evaluation at two passes is 120 requests on its own — see the
  Results section above for what actually happens when several providers hit
  this simultaneously.

---

## Architecture

```
  upload (PDF / PNG / JPG)
          │
          ▼
  ┌───────────────┐   text layer?  ──yes──►  PyMuPDF text
  │   parsing.py  │
  └───────────────┘   no ──────────────────►  render page → PNG → vision model
          │
          ▼
  ┌─────────────────────────────────────────┐
  │  extraction.py — 2 concurrent passes    │
  │  llm_router.py — OpenRouter → Groq →    │
  │                  Google, retry + fallback│
  └─────────────────────────────────────────┘
          │
          ▼
  ┌─────────────────────────────────────────┐
  │  confidence.py                          │
  │   self-report ─┐                        │
  │   agreement  ──┼──► weighted ──► status │
  │   rules      ──┘                        │
  └─────────────────────────────────────────┘
          │
          ├──► Supabase: documents + corrections
          └──► React review UI
                   │
                   └──► human correction ──► corrections table ──► /api/weakness
```

Every human correction is stored. After ~500 of them, `/api/weakness` tells you which
fields are weakest and — the useful part — **at what confidence the wrong values
escaped**, which is what you tune the thresholds against.

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| PDF parsing | PyMuPDF | Fast, no system dependencies, renders pages for the vision path |
| Scans / photos | Multimodal LLM | Beats bolting on a separate OCR engine; handles skew and bad lighting |
| LLM | OpenRouter (3 free models, see `OPENROUTER_MODELS`) → Groq → Google AI Studio (`gemini-3.5-flash`) | Free tiers rate-limit hard — not just per provider, but per *model*, at ~50 requests/day each. Several genuinely-free models are chained because one alone isn't enough headroom. Scans/photos route past text-only models straight to a vision-capable one — see `llm_router.supports_vision` |
| Validation | Pydantic | Loose at the model boundary, strict everywhere after |
| Backend | FastAPI | |
| Database | Supabase (Postgres) | |
| UI | React + TypeScript + Vite | |
| Hosting | Render free tier | |

---

## Running it

### 1. Setup

```bash
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
```

### 2. Configure

```bash
cp backend/.env.example backend/.env
```

Then edit `backend/.env`:

- `OPENROUTER_API_KEY` — free key from [openrouter.ai/keys](https://openrouter.ai/keys)
- `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` — from your Supabase project settings
- Optionally `GROQ_API_KEY` and `GOOGLE_API_KEY` as fallbacks (worth it; free tiers
  rate-limit often)

Then run `backend/supabase_schema.sql` once in the Supabase SQL editor.

The app runs without Supabase — it just stops persisting, and says so in the UI.

### 3. Generate a labelled test set

```bash
python scripts/generate_invoices.py --count 60
```

Writes 60 invoices across four layouts, with varied date formats, Indian digit
grouping, intra- vs inter-state GST, and ~15% rotated to mimic scans — plus a
`ground_truth.json` with the correct answers.

### 4. Verify the pipeline (no API key needed)

```bash
python scripts/smoke_test.py
```

Runs the whole path against a stubbed LLM and asserts what matters: that a total
which fails the arithmetic rule is **not** auto-accepted, that an invalid GSTIN is
**not** auto-accepted, that disagreeing passes lower the agreement signal, and that
empty, corrupt, and truncated files fail with a clear message rather than a 500.

### 5. Run it

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev        # in a second terminal
```

Open http://localhost:5173.

### 6. Measure it

```bash
python scripts/evaluate.py --limit 25 --tune
```

---

## Deploying

Two services on Render's free tier — a FastAPI web service and a static site,
joined by a rewrite so the browser sees one origin. Both are declared in
[`render.yaml`](render.yaml), so a Blueprint deploy needs no manual
configuration.

Full runbook, including the settings to enter if you create the services by
hand and the failure modes worth knowing about in advance:
**[DEPLOYMENT.md](DEPLOYMENT.md)**.

---

## API

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/health` | Which providers are live, thresholds, weights |
| `POST` | `/api/extract` | Upload a document, get scored fields back |
| `GET` | `/api/documents` | Recent extractions |
| `GET` | `/api/documents/{id}` | One extraction in full |
| `POST` | `/api/corrections` | Save a human correction |
| `GET` | `/api/weakness` | Which fields get corrected most, and at what confidence |

Interactive docs at `/docs`.

---

## What I'd do next

1. **Deskew and denoise before the vision path.** On photographed invoices this
   usually buys more accuracy than swapping models.
2. **Learn the weights instead of hand-setting them.** With enough corrections,
   fit a logistic regression on the three signals against correctness — turns
   `0.3/0.3/0.4` from a guess into a measured result.
3. **Per-vendor layout memory.** The same vendor sends the same layout every month;
   caching what worked last time is cheaper and more accurate than re-reasoning.
4. **Page-spanning line item stitching**, the biggest correctness gap today.

---

*Project 1 of 6 from my AI automation build plan. Project 2 (three-way PO/GRN/invoice
match) reuses this extraction layer.*

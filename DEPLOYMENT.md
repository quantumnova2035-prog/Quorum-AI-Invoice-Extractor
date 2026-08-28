# Deploying Quorum AI

Two services on Render's free tier: a FastAPI **web service** for the API, and a
**static site** for the React frontend. They are wired together by a rewrite rule
so the browser only ever talks to one origin — no CORS preflight, no API base URL
compiled into the bundle.

Everything below is already declared in [`render.yaml`](render.yaml). If you use
the Blueprint route you will not type any of it.

---

## Before you start

- A GitHub repo with this code pushed (see [First push](#first-push) if you have
  not done that yet).
- A Supabase project, with `backend/supabase_schema.sql` run once in its SQL
  editor. **Do this first.** Without it the app still works, but nothing is
  persisted and no timing or cost is recorded — which looks like a bug rather
  than a missing migration.
- At least one LLM key. OpenRouter alone is enough; Groq and Google are
  fallbacks and are worth adding, because free tiers rate-limit constantly.

---

## Route A — Blueprint (recommended)

Render reads `render.yaml` and creates both services, already connected.

1. Render Dashboard → **New +** → **Blueprint**
2. Connect the repository. For a **private** repo, Render will ask for access —
   grant it to this repo.
3. Render lists the two services and prompts for every variable marked
   `sync: false`. Fill them from your local `backend/.env`:
   - `OPENROUTER_API_KEY`
   - `GROQ_API_KEY`
   - `GOOGLE_API_KEY`
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY`
4. **Apply.**
5. Add two more variables to `quorum-ai-api` that are not in the blueprint:

   | Key | Value |
   |---|---|
   | `OPENROUTER_MODELS` | `nvidia/nemotron-3-super-120b-a12b:free,z-ai/glm-5.2:free,minimax/minimax-m2.7:free` |
   | `GOOGLE_MODEL` | `gemini-3.5-flash` |

   Without `OPENROUTER_MODELS` the router falls back to its built-in default list
   rather than your three free models.

6. Read the two real URLs off the dashboard and see
   [Hostnames are not guaranteed](#hostnames-are-not-guaranteed) below.

---

## Route B — creating the services by hand

Use this if you would rather not use a blueprint. The values are identical.

### Service 1 — API

| Field | Value |
|---|---|
| Type | **Web Service** |
| Language | **Python 3** |
| Root Directory | `backend` |
| Instance Type | Free |

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Environment variables:

| Key | Value |
|---|---|
| `PYTHON_VERSION` | `3.12.7` |
| `OPENROUTER_API_KEY` | from `backend/.env` |
| `OPENROUTER_MODELS` | `nvidia/nemotron-3-super-120b-a12b:free,z-ai/glm-5.2:free,minimax/minimax-m2.7:free` |
| `GROQ_API_KEY` | from `backend/.env` |
| `GOOGLE_API_KEY` | from `backend/.env` |
| `GOOGLE_MODEL` | `gemini-3.5-flash` |
| `SUPABASE_URL` | from `backend/.env` |
| `SUPABASE_SERVICE_KEY` | from `backend/.env` |
| `CORS_ORIGINS` | the **frontend's** real URL, e.g. `https://quorum-ai-ui.onrender.com` |

Deploy this one **first**, so you know its URL before configuring the frontend.

Check it with `https://<your-api>.onrender.com/api/health` — it should list your
providers and report `supabase: connected`.

### Service 2 — Frontend

| Field | Value |
|---|---|
| Type | **Static Site** |
| Root Directory | `frontend` |

Build command:

```bash
npm ci --include=dev && npm run build
```

Publish directory:

```
dist
```

There is **no start command**. A static site serves files; nothing runs.

Then add two rules under **Redirects/Rewrites**, in this order:

| # | Source | Destination | Action |
|---|---|---|---|
| 1 | `/api/*` | `https://<your-api>.onrender.com/api/*` | Rewrite |
| 2 | `/*` | `/index.html` | Rewrite |

Rule 1 is what lets the frontend call `/api/health` with no base URL. Rule 2 is
the single-page-app fallback, so a refresh on any route still serves the app.

**Order matters.** `/*` matches everything, so if it comes first it swallows the
API requests and rule 1 never fires.

---

## Things that will bite you

### `--include=dev` is not optional

Render builds with `NODE_ENV=production`, and npm then skips `devDependencies` —
which is where `vite` and `typescript` live. A plain `npm ci` produces:

```
sh: 1: vite: not found
```

### Hostnames are not guaranteed

`*.onrender.com` names are globally unique. If `quorum-ai-api` is taken, Render
assigns something like `quorum-ai-api-a1b2` — and then the rewrite in
`render.yaml` points at a service that does not exist, while `CORS_ORIGINS`
names a frontend that is not yours.

**Symptom:** the UI loads perfectly, and every single API call fails.

After the first deploy, read both real URLs off the dashboard and update them:

```bash
sed -i 's|quorum-ai-api.onrender.com|YOUR-REAL-API-HOST|; s|quorum-ai-ui.onrender.com|YOUR-REAL-UI-HOST|' render.yaml
git commit -am "Point services at their actual Render hostnames"
git push
```

### Free services sleep

Both spin down after ~15 minutes idle, and the first request afterwards takes
30–60 seconds. During that wake-up the health pill in the header reads
**No LLM key**, because `/api/health` has not answered yet — it corrects itself
once the service is up. If you are demoing this, load the page a minute early.

### The extraction is slow by design, and the free tier makes it slower

Two passes per document, and free-tier models rate-limit under any real load. A
document that waits on a 429 will show that wait separately in its timing
breakdown, labelled as retry time rather than model time — so a slow result is
attributable rather than mysterious.

---

## First push

If the repo is not on GitHub yet. **Never** drag-and-drop the folder into
GitHub's web uploader: it does not honour `.gitignore` and will publish
`backend/.env`, including your Supabase service key.

```bash
git init -b main
git add -A
```

Confirm nothing sensitive is staged — this must print **nothing**:

```bash
git ls-files | grep -E "\.env$|\.venv|node_modules"
```

Then:

```bash
git commit -m "Quorum AI: confidence-scored invoice extractor"
git remote add origin https://<your-username>@github.com/<your-username>/<repo>.git
git push -u origin main
```

### If git cannot authenticate

Putting the username in the remote URL is deliberate. Git looks up stored
credentials by host, so with more than one GitHub account saved in Windows
Credential Manager it picks whichever is stored under the bare `github.com` key —
which may not be the account that owns the repo. Pinning the username makes git
look up `git:https://<username>@github.com` instead and find the right one.

To see what is stored:

```bash
cmdkey /list | findstr github
```

---

## Verifying a deploy

| Check | Expectation |
|---|---|
| `https://<api>/api/health` | Lists providers; `supabase.enabled: true` |
| `https://<api>/docs` | Interactive API docs load |
| Frontend loads | Header shows **Ready**, not *No LLM key* / *Not saving* |
| Home tab | Lists past documents from Supabase |
| Upload one invoice | Completes, and its cost and time are recorded |

If the header says **Not saving**, the migration has not been run. If it says
**No LLM key**, either the service is still waking or the keys did not save.

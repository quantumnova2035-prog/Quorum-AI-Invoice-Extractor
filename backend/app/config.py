"""Central config. Everything secret comes from .env — nothing is hardcoded."""
import os
from pathlib import Path
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]   # the backend/ directory
ROOT = BACKEND.parent                           # the repository root

# backend/.env is the documented location; the project root is accepted as a
# fallback so a stray .env one level up still works instead of silently doing
# nothing.
for _candidate in (BACKEND / ".env", ROOT / ".env"):
    if _candidate.is_file():
        load_dotenv(_candidate)
        break

# --- LLM providers (router tries them in this order) ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Model IDs get retired without warning - if you see a 404 from a provider, check
# its live model list rather than assuming the key is bad. And a ":free" suffix
# is NOT optional decoration - "openai/gpt-oss-20b" (used briefly during
# development) looked free because it responded, but was actually billing real
# money ($0.03/M input, $0.13/M output) until this was caught. Verify pricing at
# https://openrouter.ai/api/v1/models before trusting a model ID here.
#
# OPENROUTER_MODELS is a comma-separated list, tried in order. Each ":free"
# model on OpenRouter is typically served by a different upstream with its own
# separate shared rate-limit pool - one model alone gets 429'd hard on a large
# batch, so several genuinely-free models in sequence survive one pool being
# saturated. All are TEXT ONLY, so scans/photos are routed past them to a
# vision-capable provider automatically (see llm_router.supports_vision).
OPENROUTER_MODELS = [m.strip() for m in os.getenv(
    "OPENROUTER_MODELS",
    "nvidia/nemotron-3-super-120b-a12b:free,z-ai/glm-5.2:free,minimax/minimax-m2.7:free",
).split(",") if m.strip()]
OPENROUTER_MODEL = OPENROUTER_MODELS[0] if OPENROUTER_MODELS else ""  # back-compat, first model

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-3.5-flash")

# Providers whose configured model cannot accept images.
TEXT_ONLY_MODELS = set(OPENROUTER_MODELS) | {"llama-3.3-70b-versatile"}

# --- Cost ---
# OpenRouter reports the real charged cost per request, so nothing here is
# needed for it. Groq and Google return token counts but no price, so cost for
# those can only be ESTIMATED from a table - and a stale price table is worse
# than no number at all, because it looks authoritative.
#
# So this ships EMPTY on purpose. With no entry for a model, the app records the
# token counts and reports the cost as unknown rather than inventing one. Fill
# it in from the provider's own pricing page when you want estimates, via
# MODEL_PRICING_USD_PER_MTOK in .env:
#
#   MODEL_PRICING_USD_PER_MTOK=gemini-3.5-flash:0.30/2.50,llama-3.3-70b-versatile:0.59/0.79
#
# Format is `model:INPUT/OUTPUT` per 1,000,000 tokens, comma separated. Anything
# priced here is flagged "estimated" in the UI so it is never confused with a
# figure the provider actually billed.
def _parse_pricing(raw: str) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        model, _, prices = entry.partition(":")
        inp, _, outp = prices.partition("/")
        try:
            out[model.strip()] = (float(inp), float(outp or inp))
        except ValueError:
            continue          # a malformed price must not take the app down
    return out


MODEL_PRICING = _parse_pricing(os.getenv("MODEL_PRICING_USD_PER_MTOK", ""))

# --- Supabase ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "") or os.getenv("SUPABASE_ANON_KEY", "")

# --- Confidence scoring weights (tuned in scripts/evaluate.py) ---
W_SELF_REPORTED = float(os.getenv("W_SELF_REPORTED", "0.30"))
W_AGREEMENT     = float(os.getenv("W_AGREEMENT", "0.30"))
W_RULES         = float(os.getenv("W_RULES", "0.40"))

# Fields at or above this are auto-accepted; below it a human reviews.
AUTO_ACCEPT_THRESHOLD = float(os.getenv("AUTO_ACCEPT_THRESHOLD", "0.85"))
REVIEW_THRESHOLD = float(os.getenv("REVIEW_THRESHOLD", "0.60"))

EXTRACTION_TEMPERATURE = 0.3
EXTRACTION_PASSES = int(os.getenv("EXTRACTION_PASSES", "2"))

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")

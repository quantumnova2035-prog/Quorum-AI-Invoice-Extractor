"""FastAPI surface for the invoice extractor."""
from __future__ import annotations
import re
import time

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import config, db, export, llm_router, parsing
from .extraction import extract
from .llm_router import AllProvidersFailed, ByoKey
from .schemas import Correction, ExtractionResult

MAX_UPLOAD_BYTES = 20 * 1024 * 1024

app = FastAPI(
    title="Quorum AI — Invoice Extractor",
    description="Extracts invoice fields and says how sure it is about each one.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in config.CORS_ORIGINS if o.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "llm_providers": llm_router.available_providers(),
        "supabase": db.status(),
        "thresholds": {
            "auto_accept": config.AUTO_ACCEPT_THRESHOLD,
            "review": config.REVIEW_THRESHOLD,
        },
        "weights": {
            "self_reported": config.W_SELF_REPORTED,
            "agreement": config.W_AGREEMENT,
            "rules": config.W_RULES,
        },
        "passes": config.EXTRACTION_PASSES,
    }


# A model id is `vendor/name` with an optional `:suffix` - the shape OpenRouter
# uses. Validating the shape rather than an allowlist is deliberate: the picker
# in the UI is a convenience, not a cage, and models get retired often enough
# that a hardcoded list would break working setups. A wrong id fails at
# OpenRouter with a clear 404, which is a better error than "not on our list".
_MODEL_ID = re.compile(r"^[A-Za-z0-9._-]{1,60}/[A-Za-z0-9._-]{1,80}(:[A-Za-z0-9._-]{1,20})?$")


def _byo_from_headers(key: str | None, model: str | None) -> ByoKey | None:
    """Build the per-request override, or None to use the server's own chain.

    Both header values are supplied by the browser and neither is trusted: the
    key is length-checked and rejected if it carries whitespace or control
    characters (which would let it split a header downstream), and the model is
    shape-checked before it reaches a URL or a request body. Nothing here is
    logged - the whole point is that this value passes through without leaving
    a trace on the server.
    """
    if not key:
        return None
    key = key.strip()
    if not key or len(key) > 200 or any(c.isspace() or ord(c) < 32 for c in key):
        raise HTTPException(400, "That API key does not look like a key.")
    model = (model or "").strip()
    if not _MODEL_ID.match(model):
        raise HTTPException(400, "Pick a model to use with your key.")
    return ByoKey(api_key=key, model=model)


@app.post("/api/extract", response_model=ExtractionResult)
async def extract_endpoint(
    file: UploadFile = File(...),
    # Headers, not query parameters or form fields: a query string is written
    # to access logs and browser history verbatim, and this is a credential.
    x_llm_key: str | None = Header(default=None, alias="X-LLM-Key"),
    x_llm_model: str | None = Header(default=None, alias="X-LLM-Model"),
):
    byo = _byo_from_headers(x_llm_key, x_llm_model)
    data = await file.read()

    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File is larger than {MAX_UPLOAD_BYTES // 1024 // 1024} MB.")
    # With a caller-supplied key the server's own providers are irrelevant, so
    # having none configured is not a reason to refuse the request.
    if not byo and not llm_router.available_providers():
        raise HTTPException(
            503, "No LLM provider configured. Add OPENROUTER_API_KEY to backend/.env.")

    parse_started = time.perf_counter()
    doc = parsing.parse(data, file.filename or "upload")
    parse_ms = (time.perf_counter() - parse_started) * 1000

    try:
        result = await extract(doc, file.filename or "upload",
                               parse_ms=parse_ms, byo=byo)
    except AllProvidersFailed as e:
        raise HTTPException(502, f"Every LLM provider failed: {e}") from e

    db_started = time.perf_counter()
    result.document_id = db.save_document(result)
    result.timing.db_ms = round((time.perf_counter() - db_started) * 1000, 1)
    result.timing.total_ms = round(result.timing.total_ms + result.timing.db_ms, 1)
    return result


@app.get("/api/documents")
def documents(limit: int = 50):
    return db.list_documents(limit)


@app.get("/api/documents/{doc_id}")
def document(doc_id: str):
    row = db.get_document(doc_id)
    if row is None:
        raise HTTPException(404, "Document not found (or Supabase is not configured).")
    return row


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    if not db.enabled():
        raise HTTPException(503, "Supabase is not configured - nothing to delete.")
    if db.get_document(doc_id) is None:
        raise HTTPException(404, "Document not found.")
    if not db.delete_document(doc_id):
        raise HTTPException(500, "Delete failed.")
    return {"deleted": True}


def _csv_response(csv_text: str, filename: str) -> StreamingResponse:
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export/csv")
def export_csv(limit: int = 200, only_clean: bool = False):
    """One row per line item, invoice fields repeated — the shape a QuickBooks/
    Zoho Books/Tally "Import Bills" screen expects. only_clean=true drops any
    document that still has a field waiting on human review, so what comes out
    is only data that's actually been signed off."""
    if not db.enabled():
        raise HTTPException(503, "Supabase is not configured - nothing to export.")
    docs = db.list_documents_for_export(limit)
    csv_text = export.build_csv(docs, only_clean=only_clean)
    return _csv_response(csv_text, "invoices_export.csv")


@app.get("/api/documents/{doc_id}/export.csv")
def export_document_csv(doc_id: str):
    row = db.get_document(doc_id)
    if row is None:
        raise HTTPException(404, "Document not found (or Supabase is not configured).")
    csv_text = export.build_csv([row])
    safe_name = (row.get("filename") or doc_id).rsplit(".", 1)[0]
    return _csv_response(csv_text, f"{safe_name}.csv")


@app.post("/api/corrections")
def correction(corr: Correction):
    if not db.save_correction(corr):
        raise HTTPException(503, "Could not save the correction - Supabase is not configured.")
    return {"saved": True}


@app.get("/api/weakness")
def weakness():
    """Where the system is actually weak, learned from human corrections."""
    return db.weakness_report()

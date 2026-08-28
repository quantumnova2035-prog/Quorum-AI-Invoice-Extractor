"""FastAPI surface for the invoice extractor."""
from __future__ import annotations
import time

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import config, db, llm_router, parsing
from .extraction import extract
from .llm_router import AllProvidersFailed
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


@app.post("/api/extract", response_model=ExtractionResult)
async def extract_endpoint(file: UploadFile = File(...)):
    data = await file.read()

    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File is larger than {MAX_UPLOAD_BYTES // 1024 // 1024} MB.")
    if not llm_router.available_providers():
        raise HTTPException(
            503, "No LLM provider configured. Add OPENROUTER_API_KEY to backend/.env.")

    parse_started = time.perf_counter()
    doc = parsing.parse(data, file.filename or "upload")
    parse_ms = (time.perf_counter() - parse_started) * 1000

    try:
        result = await extract(doc, file.filename or "upload", parse_ms=parse_ms)
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


@app.post("/api/corrections")
def correction(corr: Correction):
    if not db.save_correction(corr):
        raise HTTPException(503, "Could not save the correction - Supabase is not configured.")
    return {"saved": True}


@app.get("/api/weakness")
def weakness():
    """Where the system is actually weak, learned from human corrections."""
    return db.weakness_report()

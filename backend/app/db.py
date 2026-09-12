"""Supabase persistence, behind one small interface.

If Supabase isn't configured the app still runs - it just doesn't persist. That
keeps the demo alive when the free tier is asleep or a key is missing, and it
means you can run the whole pipeline offline while developing.
"""
from __future__ import annotations
import json
from typing import Any, Optional

from . import config
from .schemas import Correction, ExtractionResult

_client = None
_init_error: Optional[str] = None


def client():
    global _client, _init_error
    if _client is not None or _init_error is not None:
        return _client
    if not (config.SUPABASE_URL and config.SUPABASE_KEY):
        _init_error = "Supabase not configured (SUPABASE_URL / SUPABASE_SERVICE_KEY missing)."
        return None
    try:
        from supabase import create_client
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    except Exception as e:  # noqa: BLE001
        _init_error = f"Supabase client failed to initialise: {e}"
    return _client


def enabled() -> bool:
    return client() is not None


def status() -> dict[str, Any]:
    return {"enabled": enabled(), "detail": _init_error or "connected"}


def save_document(result: ExtractionResult) -> Optional[str]:
    """Persist one extraction. Returns the document id, or None if not persisted."""
    c = client()
    if c is None:
        return None
    row = {
        "filename": result.filename,
        "source": result.source,
        "provider": result.provider,
        "overall_confidence": result.overall_confidence,
        "auto_accept_rate": result.auto_accept_rate,
        "fields": json.loads(json.dumps([f.model_dump() for f in result.fields])),
        "line_items": json.loads(json.dumps([li.model_dump() for li in result.line_items])),
        "warnings": result.warnings,
        "raw_text_preview": result.raw_text_preview,
        "timing": json.loads(result.timing.model_dump_json()),
        "total_ms": result.timing.total_ms,
        "cost": json.loads(result.cost.model_dump_json()),
        "cost_usd": result.cost.total_usd if result.cost.known else None,
    }
    try:
        res = c.table("documents").insert(row).execute()
        return res.data[0]["id"] if res.data else None
    except Exception as e:  # noqa: BLE001
        # A database created before the timing columns existed will reject the
        # insert outright. Losing the whole extraction over a missing metrics
        # column would be a bad trade, so drop the new fields and save the part
        # that matters - then say the timing was not stored, rather than
        # letting it look like it was.
        if _is_missing_column(e):
            for k in ("timing", "total_ms", "cost", "cost_usd"):
                row.pop(k, None)
            try:
                res = c.table("documents").insert(row).execute()
                result.warnings.append(
                    "Timing and cost were not saved - the database is missing those "
                    "columns. Re-run backend/supabase_schema.sql to add them.")
                return res.data[0]["id"] if res.data else None
            except Exception as e2:  # noqa: BLE001
                e = e2
        result.warnings.append(f"Could not save to Supabase: {e}")
        return None


def _is_missing_column(e: Exception) -> bool:
    msg = str(e).lower()
    # PostgREST reports an unknown column as PGRST204 / "could not find the
    # column"; Postgres itself says "column ... does not exist".
    known = ("timing", "total_ms", "cost", "cost_usd")
    return ("pgrst204" in msg
            or "could not find" in msg
            or "does not exist" in msg) and any(k in msg for k in known)


def list_documents(limit: int = 50) -> list[dict[str, Any]]:
    c = client()
    if c is None:
        return []
    try:
        res = (c.table("documents")
               .select("id, filename, source, provider, overall_confidence, "
                       "auto_accept_rate, created_at, total_ms, cost_usd")
               .order("created_at", desc=True).limit(limit).execute())
        return res.data or []
    except Exception as e:  # noqa: BLE001
        # Fall back to the pre-timing column set so History still loads against
        # a database that has not been migrated yet.
        if _is_missing_column(e):
            try:
                res = (c.table("documents")
                       .select("id, filename, source, provider, overall_confidence, "
                               "auto_accept_rate, created_at")
                       .order("created_at", desc=True).limit(limit).execute())
                return res.data or []
            except Exception:  # noqa: BLE001
                return []
        return []


def list_documents_for_export(limit: int = 200) -> list[dict[str, Any]]:
    """Like list_documents, but pulls the columns CSV export actually needs
    (fields + line_items), which the History-list query deliberately omits to
    keep that request light."""
    c = client()
    if c is None:
        return []
    try:
        res = (c.table("documents")
               .select("id, filename, fields, line_items, overall_confidence, "
                       "auto_accept_rate, created_at")
               .order("created_at", desc=True).limit(limit).execute())
        return res.data or []
    except Exception:  # noqa: BLE001
        return []


def delete_document(doc_id: str) -> bool:
    """Corrections cascade-delete with their document (see supabase_schema.sql's
    ON DELETE CASCADE), so removing a document also cleans up its corrections."""
    c = client()
    if c is None:
        return False
    try:
        res = c.table("documents").delete().eq("id", doc_id).execute()
        return bool(res.data)
    except Exception:  # noqa: BLE001
        return False


def get_document(doc_id: str) -> Optional[dict[str, Any]]:
    c = client()
    if c is None:
        return None
    try:
        res = c.table("documents").select("*").eq("id", doc_id).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception:  # noqa: BLE001
        return None


def save_correction(corr: Correction) -> bool:
    """Every human correction is training data. After 500 of these you know
    exactly which fields your system is weakest on - see /api/weakness."""
    c = client()
    if c is None:
        return False
    try:
        c.table("corrections").insert({
            "document_id": corr.document_id,
            "field_name": corr.field_name,
            "original_value": None if corr.original_value is None else str(corr.original_value),
            "corrected_value": None if corr.corrected_value is None else str(corr.corrected_value),
            "original_confidence": corr.original_confidence,
        }).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


def weakness_report() -> list[dict[str, Any]]:
    """Which fields get corrected most, and at what confidence they slipped through."""
    c = client()
    if c is None:
        return []
    try:
        rows = (c.table("corrections")
                .select("field_name, original_confidence").limit(5000).execute()).data or []
    except Exception:  # noqa: BLE001
        return []

    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        f = agg.setdefault(r["field_name"], {"field_name": r["field_name"],
                                             "corrections": 0, "confs": []})
        f["corrections"] += 1
        if r.get("original_confidence") is not None:
            f["confs"].append(float(r["original_confidence"]))

    out = []
    for f in agg.values():
        confs = f.pop("confs")
        f["avg_confidence_when_wrong"] = round(sum(confs) / len(confs), 3) if confs else None
        # A correction on a field we auto-accepted is an escaped error - the
        # number that actually matters.
        f["escaped_auto_accept"] = sum(
            1 for x in confs if x >= config.AUTO_ACCEPT_THRESHOLD)
        out.append(f)
    return sorted(out, key=lambda x: -x["corrections"])

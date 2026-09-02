"""Orchestrates: parsed document -> N independent LLM passes -> scored fields."""
from __future__ import annotations
import asyncio, time
from typing import Any, Optional

from pydantic import ValidationError

from . import config, confidence
from .llm_router import AllProvidersFailed, ByoKey, LLMCall, complete_json
from .parsing import ParsedDocument
from .schemas import (CallTiming, Cost, ExtractionResult, InvoiceFields, LineItem,
                      LLMInvoiceResponse, RawLineItem, Timing)

SYSTEM_PROMPT = """You are an invoice data extraction engine for an accounts payable team.

Return ONLY a JSON object matching this shape:
{
  "vendor_name": string|null,
  "vendor_gstin": string|null,
  "vendor_address": string|null,
  "buyer_name": string|null,
  "buyer_gstin": string|null,
  "invoice_number": string|null,
  "invoice_date": "YYYY-MM-DD"|null,
  "due_date": "YYYY-MM-DD"|null,
  "currency": "INR"|"USD"|...,
  "subtotal": number|null,
  "tax_amount": number|null,
  "total_amount": number|null,
  "line_items": [
    {"description": string, "quantity": number|null, "unit_price": number|null,
     "amount": number|null, "hsn_sac": string|null}
  ],
  "confidence": { "<field_name>": 0.0-1.0, ... }
}

Rules:
- The VENDOR is whoever issued the invoice and is owed money. The BUYER is whoever
  is billed. Do not swap them - "Bill To" is the buyer.
- Numbers must be plain numbers: 124500.00, not "Rs. 1,24,500/-".
- Dates must be ISO YYYY-MM-DD. Indian invoices normally write DD/MM/YYYY.
- tax_amount is the total of CGST + SGST + IGST + any cess.
- Use null for anything genuinely not on the document. Never invent a value.
- In "confidence", give an honest 0-1 score per field. Score low when the text was
  unclear, ambiguous, or you had to guess.
- Output JSON only. No commentary, no markdown fences."""

USER_TEMPLATE = """Extract the invoice below.

--- DOCUMENT TEXT ---
{text}
--- END ---"""

IMAGE_USER_TEMPLATE = """Extract the invoice from the attached image(s). Read carefully;
the scan may be skewed, low contrast, or photographed at an angle.

{text}"""

MAX_TEXT_CHARS = 24_000


def _unwrap(raw: Any) -> dict[str, Any]:
    """Models occasionally return a JSON array instead of the requested object -
    e.g. `[{...invoice fields...}]`, or just the line items as a bare list. Rather
    than crash the pass on `raw.items()`, unwrap the common shapes and fall back
    to an empty object (which scores every field as missing, not the whole pass
    as failed) for anything genuinely unrecognisable.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        dicts = [x for x in raw if isinstance(x, dict)]
        if len(dicts) == 1:
            return dicts[0]
        # A list of dicts that look like line items rather than one invoice.
        if dicts and any(k in dicts[0] for k in ("description", "amount", "unit_price")):
            return {"line_items": dicts}
    return {}


def _coerce(raw: Any) -> tuple[InvoiceFields, dict[str, float]]:
    """Force whatever the model returned into our schema, normalizing as we go."""
    raw = _unwrap(raw)
    try:
        parsed = LLMInvoiceResponse.model_validate(raw)
    except ValidationError:
        # Salvage the scalar fields rather than losing the whole pass to a
        # malformed line_items array.
        cleaned = {k: v for k, v in raw.items()
                   if k in LLMInvoiceResponse.model_fields and k != "line_items"}
        parsed = LLMInvoiceResponse.model_validate(cleaned)
        parsed.line_items = _salvage_line_items(raw.get("line_items"))

    data: dict[str, Any] = {}
    for name in confidence.SCALAR_FIELDS:
        data[name] = confidence.normalize_value(name, getattr(parsed, name, None))
    data["line_items"] = _normalize_line_items(parsed.line_items)

    self_conf: dict[str, float] = {}
    for k, v in (parsed.confidence or {}).items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if 0.0 <= fv <= 1.0:
            self_conf[k] = fv
    return InvoiceFields(**data), self_conf


def _salvage_line_items(raw: Any) -> list[RawLineItem]:
    if not isinstance(raw, list):
        return []
    out: list[RawLineItem] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                out.append(RawLineItem.model_validate(
                    {k: v for k, v in item.items() if k in RawLineItem.model_fields}))
            except ValidationError:
                continue
    return out


def _num(v: Any) -> float | None:
    return None if v is None else confidence._normalize_money(v)


def _normalize_line_items(items: list[RawLineItem]) -> list[LineItem]:
    out = []
    for it in items:
        out.append(LineItem(
            description=confidence.normalize_value("description", it.description),
            quantity=_num(it.quantity),
            unit_price=_num(it.unit_price),
            amount=_num(it.amount),
            hsn_sac=None if it.hsn_sac is None else str(it.hsn_sac),
        ))
    return out


async def _one_pass(doc: ParsedDocument,
                    byo: ByoKey | None = None,
                    ) -> tuple[InvoiceFields, dict[str, float], LLMCall]:
    text = (doc.text or "")[:MAX_TEXT_CHARS]
    if doc.images_b64:
        user = IMAGE_USER_TEMPLATE.format(
            text=f"Any machine-readable text found:\n{text}" if text.strip() else "")
        call = await complete_json(
            SYSTEM_PROMPT, user, config.EXTRACTION_TEMPERATURE,
            images=doc.images_b64, byo=byo)
    else:
        call = await complete_json(
            SYSTEM_PROMPT, USER_TEMPLATE.format(text=text),
            config.EXTRACTION_TEMPERATURE, byo=byo)
    fields, self_conf = _coerce(call.data)
    return fields, self_conf, call


def _sum_cost(calls: list[CallTiming]) -> Cost:
    """Total one document's passes.

    Passes with no reported price are counted as unknown rather than as zero -
    otherwise a partial sum would be displayed as though it were the full bill.
    """
    priced = [c for c in calls if c.cost_usd is not None]
    return Cost(
        total_usd=round(sum(c.cost_usd or 0.0 for c in priced), 6),
        prompt_tokens=sum(c.prompt_tokens or 0 for c in calls),
        completion_tokens=sum(c.completion_tokens or 0 for c in calls),
        known=len(priced) == len(calls) and bool(calls),
        is_estimated=any(c.cost_is_estimated for c in priced),
        # "Free" is a claim about what was reported, so it needs every pass to
        # have actually reported - not merely to have summed to zero.
        free=bool(calls) and len(priced) == len(calls)
             and all((c.cost_usd or 0.0) == 0.0 for c in priced),
    )


async def extract(doc: ParsedDocument, filename: str,
                  parse_ms: float = 0.0,
                  byo: ByoKey | None = None) -> ExtractionResult:
    """Run N passes concurrently, then score. Two passes is the sweet spot: it
    doubles cost but gives us the agreement signal, which is worth far more than
    the model's own opinion of itself.

    `parse_ms` is measured by the caller, since parsing happens before this is
    reached; it is threaded through only so one Timing object describes the
    whole document rather than half of it.
    """
    warnings = list(doc.warnings)
    started = time.perf_counter()

    if not doc.usable:
        return ExtractionResult(
            filename=filename, source=doc.source, provider="none",
            fields=confidence.score_fields([InvoiceFields()], [{}]),
            warnings=warnings + ["Extraction skipped - nothing readable in the file."],
            timing=Timing(parse_ms=parse_ms, total_ms=parse_ms),
        )

    n = max(1, config.EXTRACTION_PASSES)
    llm_started = time.perf_counter()
    outcomes = await asyncio.gather(*[_one_pass(doc, byo) for _ in range(n)],
                                    return_exceptions=True)
    llm_ms = (time.perf_counter() - llm_started) * 1000

    passes: list[InvoiceFields] = []
    self_reported: list[dict[str, float]] = []
    calls: list[CallTiming] = []
    provider = "unknown"
    degenerate = 0
    for i, res in enumerate(outcomes):
        if isinstance(res, BaseException):
            if isinstance(res, AllProvidersFailed):
                warnings.append(f"An extraction pass failed: {res}")
            else:
                warnings.append(f"An extraction pass errored: {type(res).__name__}: {res}")
            continue
        fields, self_conf, call = res
        provider = call.provider

        # Record the timing even for a pass that turns out to be degenerate -
        # it still took real time and still hit the provider, so leaving it out
        # would make a slow document look faster than it was.
        calls.append(CallTiming(
            pass_index=i, provider=call.provider, model=call.model,
            latency_ms=call.latency_ms, wasted_ms=call.wasted_ms,
            attempts=call.attempts,
            prompt_tokens=call.prompt_tokens,
            completion_tokens=call.completion_tokens,
            cost_usd=call.cost_usd,
            cost_is_estimated=call.cost_is_estimated,
        ))

        # A pass can come back HTTP 200 but nearly empty - a truncated or
        # malformed completion under load, seen in practice on free-tier
        # models under concurrent traffic. That's not a partial answer worth
        # blending in; it's a failed pass wearing a success status code, and
        # letting it through silently drags every field's agreement score down
        # with no visible explanation. Drop it and say so instead.
        filled = sum(1 for name in confidence.SCALAR_FIELDS if getattr(fields, name, None) is not None)
        if filled <= 1:
            degenerate += 1
            continue

        passes.append(fields)
        self_reported.append(self_conf)

    if degenerate:
        warnings.append(
            f"{degenerate} extraction pass(es) returned almost no data (a truncated or "
            "malformed response, typically under heavy load on a free-tier model) and "
            "were discarded rather than counted.")

    if not passes:
        raise AllProvidersFailed(
            "; ".join(warnings) or "every extraction pass failed")

    if len(passes) < n:
        warnings.append(
            f"Only {len(passes)} of {n} passes succeeded - the agreement signal is weaker, "
            "so confidence scores are more conservative.")

    scoring_started = time.perf_counter()
    scored = confidence.score_fields(passes, self_reported)
    scoring_ms = (time.perf_counter() - scoring_started) * 1000

    filled = [f for f in scored if f.value is not None]
    auto = [f for f in filled if f.status == "auto_accept"]

    cost = _sum_cost(calls)
    if cost.total_usd > 0:
        # A model believed to be free that starts reporting a price is the most
        # expensive kind of silent failure, so it is surfaced on the document
        # itself rather than left for a billing page to reveal weeks later.
        warnings.append(
            f"This document cost ${cost.total_usd:.4f}"
            f"{' (estimated)' if cost.is_estimated else ''}. If you expected a free "
            "model, check the model IDs in OPENROUTER_MODELS - a `:free` suffix is "
            "the only thing that makes a model free.")

    retried = [c for c in calls if c.attempts > 1]
    if retried:
        wasted = sum(c.wasted_ms for c in retried)
        warnings.append(
            f"{len(retried)} pass(es) had to retry or fall back to another provider, "
            f"adding {wasted / 1000:.1f}s. The extraction itself was not slow - it was "
            "waiting on a provider that refused.")

    return ExtractionResult(
        filename=filename,
        source=doc.source,
        provider=provider,
        fields=scored,
        line_items=passes[0].line_items,
        overall_confidence=round(sum(f.confidence for f in filled) / len(filled), 3) if filled else 0.0,
        auto_accept_rate=round(len(auto) / len(filled), 3) if filled else 0.0,
        raw_text_preview=(doc.text or "")[:2000],
        warnings=warnings,
        cost=cost,
        timing=Timing(
            parse_ms=round(parse_ms, 1),
            llm_ms=round(llm_ms, 1),
            scoring_ms=round(scoring_ms, 1),
            total_ms=round(parse_ms + (time.perf_counter() - started) * 1000, 1),
            calls=calls,
        ),
    )

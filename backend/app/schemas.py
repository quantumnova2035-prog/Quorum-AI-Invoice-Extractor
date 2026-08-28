"""Pydantic schema the LLM output is forced into, plus API response models."""
from __future__ import annotations
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None
    hsn_sac: Optional[str] = None


class InvoiceFields(BaseModel):
    """The fields we extract. Everything optional — a missing field is a real
    outcome, not an error, and it must not blow up validation."""
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    vendor_address: Optional[str] = None
    buyer_name: Optional[str] = None
    buyer_gstin: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = Field(None, description="ISO YYYY-MM-DD")
    due_date: Optional[str] = Field(None, description="ISO YYYY-MM-DD")
    currency: Optional[str] = "INR"
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    total_amount: Optional[float] = None
    line_items: List[LineItem] = Field(default_factory=list)


class RawLineItem(BaseModel):
    """Line item straight off the model — every field loose, normalized later."""
    description: Optional[Any] = None
    quantity: Optional[Any] = None
    unit_price: Optional[Any] = None
    amount: Optional[Any] = None
    hsn_sac: Optional[Any] = None


class LLMInvoiceResponse(BaseModel):
    """What the model actually returns.

    Deliberately loosely typed. Models return "Rs. 1,24,500/-" and "12/03/2024"
    no matter how firmly the prompt asks for numbers and ISO dates. Strictly
    typing this here would throw away an otherwise perfect extraction over one
    currency symbol, so parsing happens in extraction._coerce instead.
    """
    vendor_name: Optional[Any] = None
    vendor_gstin: Optional[Any] = None
    vendor_address: Optional[Any] = None
    buyer_name: Optional[Any] = None
    buyer_gstin: Optional[Any] = None
    invoice_number: Optional[Any] = None
    invoice_date: Optional[Any] = None
    due_date: Optional[Any] = None
    currency: Optional[Any] = None
    subtotal: Optional[Any] = None
    tax_amount: Optional[Any] = None
    total_amount: Optional[Any] = None
    line_items: List[RawLineItem] = Field(default_factory=list)
    confidence: Dict[str, Any] = Field(default_factory=dict)


class FieldResult(BaseModel):
    name: str
    value: Any = None
    confidence: float = 0.0
    status: str = "review"            # auto_accept | review | reject
    self_reported: float = 0.0
    agreement: float = 0.0
    rules: float = 0.0
    rule_notes: List[str] = Field(default_factory=list)


class CallTiming(BaseModel):
    """One LLM pass: who answered, how long it took, what it cost in retries."""
    pass_index: int
    provider: str
    model: str
    latency_ms: float = 0.0
    wasted_ms: float = 0.0             # failed attempts + backoff before success
    attempts: int = 1
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cost_usd: Optional[float] = None       # None = provider did not report a price
    cost_is_estimated: bool = False


class Cost(BaseModel):
    """What one document cost, summed across all its passes.

    `total_usd` is only meaningful alongside `known`: if some passes did not
    report a price, the total is a floor, not the answer. Presenting a partial
    sum as if it were complete is the exact mistake that let a paid model look
    free for a whole afternoon.
    """
    total_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    known: bool = True                 # every pass reported (or priced) a cost
    is_estimated: bool = False         # at least one figure came from the table
    free: bool = False                 # every pass reported exactly zero


class Timing(BaseModel):
    """Where a document's wall-clock time actually went.

    `total_ms` is real elapsed time. The phases do NOT sum to it, and that is
    deliberate: the extraction passes run concurrently, so `llm_ms` is the
    wall-clock span of the whole gather while `calls[].latency_ms` are the
    individual (overlapping) requests. Showing both is what makes the
    concurrency visible instead of implied.
    """
    parse_ms: float = 0.0
    llm_ms: float = 0.0                # wall clock across all passes
    scoring_ms: float = 0.0
    db_ms: float = 0.0
    total_ms: float = 0.0
    calls: List[CallTiming] = Field(default_factory=list)

    @property
    def llm_serial_ms(self) -> float:
        """What the passes would have cost run one after another."""
        return round(sum(c.latency_ms for c in self.calls), 1)


class ExtractionResult(BaseModel):
    document_id: Optional[str] = None
    filename: str
    source: str                        # text_pdf | ocr_image | fallback
    provider: str                      # which LLM answered
    fields: List[FieldResult]
    line_items: List[LineItem] = Field(default_factory=list)
    overall_confidence: float = 0.0
    auto_accept_rate: float = 0.0
    raw_text_preview: str = ""
    warnings: List[str] = Field(default_factory=list)
    timing: Timing = Field(default_factory=Timing)
    cost: Cost = Field(default_factory=Cost)


class Correction(BaseModel):
    document_id: str
    field_name: str
    original_value: Optional[str] = None
    corrected_value: Optional[str] = None
    original_confidence: Optional[float] = None

"""CSV export — the one format every accounting tool accepts via "Import".

Deliberately not a dump of the internal schema. The columns here are the ones
a bill-import screen (QuickBooks, Zoho Books, Tally's XML-via-CSV-staging, or
a plain "hand this to our accountant") actually wants: one row per line item,
with the invoice-level fields repeated on every row, which is the shape all of
those tools expect when a bill has multiple items.

Kept deliberately dumb: no auth, no per-vendor mapping, no API calls. If a
document has no line items at all, it still gets exactly one row so nothing
silently disappears from the export.
"""
from __future__ import annotations
import csv
import io
from typing import Any, Iterable

from . import config

COLUMNS = [
    "filename",
    "invoice_number",
    "invoice_date",
    "due_date",
    "vendor_name",
    "vendor_gstin",
    "vendor_address",
    "buyer_name",
    "buyer_gstin",
    "currency",
    "item_description",
    "item_hsn_sac",
    "item_quantity",
    "item_unit_price",
    "item_amount",
    "subtotal",
    "tax_amount",
    "total_amount",
    "overall_confidence",
    "review_status",
]


def _field_value(fields: list[dict[str, Any]], name: str) -> Any:
    """Pull one named field's value out of the stored FieldResult list.

    Fields are stored as a flat list of {name, value, confidence, status, ...}
    rather than a dict, so this is a linear lookup — invoices have a couple
    dozen fields at most, not worth indexing.
    """
    for f in fields:
        if f.get("name") == name:
            return f.get("value")
    return None


def _review_status(doc: dict[str, Any]) -> str:
    rate = doc.get("auto_accept_rate")
    if rate is None:
        return "unknown"
    return "clean" if rate >= config.AUTO_ACCEPT_THRESHOLD else "needs_review"


def rows_for_document(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """One document -> one or more flat rows, one per line item."""
    fields = doc.get("fields") or []
    line_items = doc.get("line_items") or []

    header = {
        "filename": doc.get("filename", ""),
        "invoice_number": _field_value(fields, "invoice_number") or "",
        "invoice_date": _field_value(fields, "invoice_date") or "",
        "due_date": _field_value(fields, "due_date") or "",
        "vendor_name": _field_value(fields, "vendor_name") or "",
        "vendor_gstin": _field_value(fields, "vendor_gstin") or "",
        "vendor_address": _field_value(fields, "vendor_address") or "",
        "buyer_name": _field_value(fields, "buyer_name") or "",
        "buyer_gstin": _field_value(fields, "buyer_gstin") or "",
        "currency": _field_value(fields, "currency") or "",
        "subtotal": _field_value(fields, "subtotal"),
        "tax_amount": _field_value(fields, "tax_amount"),
        "total_amount": _field_value(fields, "total_amount"),
        "overall_confidence": round(doc.get("overall_confidence") or 0.0, 3),
        "review_status": _review_status(doc),
    }

    if not line_items:
        row = dict(header)
        row.update({
            "item_description": "", "item_hsn_sac": "",
            "item_quantity": "", "item_unit_price": "", "item_amount": "",
        })
        return [row]

    rows = []
    for li in line_items:
        row = dict(header)
        row.update({
            "item_description": li.get("description") or "",
            "item_hsn_sac": li.get("hsn_sac") or "",
            "item_quantity": li.get("quantity"),
            "item_unit_price": li.get("unit_price"),
            "item_amount": li.get("amount"),
        })
        rows.append(row)
    return rows


def build_csv(docs: Iterable[dict[str, Any]], only_clean: bool = False) -> str:
    """Documents (as returned by db.list_documents_for_export) -> CSV text.

    only_clean=True drops any document whose auto_accept_rate is below the
    configured threshold — i.e. it still has fields waiting on a human. Piping
    unreviewed numbers into an accounting system defeats the point of the
    review step, so this is off by default but there for a "only export what's
    actually been signed off" workflow.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for doc in docs:
        if only_clean and _review_status(doc) != "clean":
            continue
        for row in rows_for_document(doc):
            writer.writerow(row)
    return buf.getvalue()

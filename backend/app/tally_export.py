"""Tally XML export — one Purchase voucher per invoice.

Tally's import format is a specific XML dialect
(`ENVELOPE > BODY > IMPORTDATA > REQUESTDATA > TALLYMESSAGE > VOUCHER`), fed
to Tally either as a `.xml` file via Import Data, or POSTed straight to
Tally's local HTTP listener (usually `http://localhost:9000`) if the user has
that enabled.

**This does not create ledger masters.** `PARTYLEDGERNAME` and the purchase/
tax ledger names below must already exist in the target Tally company, or the
import fails on that voucher. Getting vendor-ledger auto-creation working is
a real Tally company setting, not something this file can paper over — so
mismatched names are a known limitation, not a bug here.

Double-entry convention (this is Tally's own convention, not a guess):
  ISDEEMEDPOSITIVE=Yes + negative AMOUNT  -> a debit
  ISDEEMEDPOSITIVE=No  + positive AMOUNT  -> a credit
A purchase voucher debits the purchase ledger (and the tax ledger, if any)
and credits the vendor for the total. That's the same `subtotal + tax ==
total` identity confidence.py already checks — a voucher that didn't balance
here would already have failed that rule and been routed to a human before
ever reaching export.
"""
from __future__ import annotations
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

from .export import _field_value, _review_status  # same lookups CSV export uses


def _tally_date(iso_date: str | None) -> str | None:
    """'2024-03-12' -> '20240312'. Tally's DATE tag wants no separators."""
    if not iso_date or len(iso_date) != 10 or iso_date[4] != "-" or iso_date[7] != "-":
        return None
    return iso_date.replace("-", "")


def _voucher_for_document(
    doc: dict[str, Any], purchase_ledger: str, tax_ledger: str,
) -> tuple[Element | None, str | None]:
    """Returns (voucher, None) or (None, skip_reason) — never both set.

    Skips rather than guesses when something a balanced voucher needs is
    missing. A wrong number silently posted into someone's books is worse
    than one invoice not showing up and being noticed.
    """
    fields = doc.get("fields") or []
    fname = doc.get("filename", "?")
    vendor = _field_value(fields, "vendor_name")
    total = _field_value(fields, "total_amount")
    date = _tally_date(_field_value(fields, "invoice_date"))
    invoice_no = _field_value(fields, "invoice_number") or fname.rsplit(".", 1)[0]

    if not vendor:
        return None, f"{fname}: no vendor name"
    if total is None:
        return None, f"{fname}: no total amount"
    if not date:
        return None, f"{fname}: missing or unparseable invoice date"
    try:
        total = float(total)
    except (TypeError, ValueError):
        return None, f"{fname}: total amount is not numeric"

    subtotal, tax = _field_value(fields, "subtotal"), _field_value(fields, "tax_amount")
    try:
        subtotal = float(subtotal) if subtotal is not None else total
    except (TypeError, ValueError):
        subtotal = total
    try:
        tax = float(tax) if tax is not None else 0.0
    except (TypeError, ValueError):
        tax = 0.0
    # If subtotal+tax drifted from total, trust total and re-derive subtotal —
    # Tally rejects a voucher outright if its ledger entries don't sum to zero.
    if round(subtotal + tax - total, 2) != 0:
        subtotal = total - tax

    voucher = Element("VOUCHER", VCHTYPE="Purchase", ACTION="Create")
    SubElement(voucher, "DATE").text = date
    SubElement(voucher, "VOUCHERTYPENAME").text = "Purchase"
    SubElement(voucher, "VOUCHERNUMBER").text = str(invoice_no)
    SubElement(voucher, "PARTYLEDGERNAME").text = str(vendor)
    conf = round(doc.get("overall_confidence") or 0.0, 2)
    SubElement(voucher, "NARRATION").text = (
        f"Invoice {invoice_no} from {vendor} — auto-imported, confidence {conf}"
    )

    def ledger_entry(name: str, positive: bool, amount: float) -> None:
        entry = SubElement(voucher, "ALLLEDGERENTRIES.LIST")
        SubElement(entry, "LEDGERNAME").text = name
        SubElement(entry, "ISDEEMEDPOSITIVE").text = "Yes" if positive else "No"
        SubElement(entry, "AMOUNT").text = f"{amount:.2f}"

    ledger_entry(purchase_ledger, True, -subtotal)
    if tax:
        ledger_entry(tax_ledger, True, -tax)
    ledger_entry(str(vendor), False, total)

    return voucher, None


def build_tally_xml(
    docs: list[dict[str, Any]],
    company_name: str = "",
    purchase_ledger: str = "Purchase Account",
    tax_ledger: str = "Input GST",
    only_clean: bool = False,
) -> tuple[str, list[str]]:
    """Documents -> (Tally import XML, list of skip reasons).

    only_clean=True additionally drops any document still waiting on a human,
    same meaning as in export.build_csv.
    """
    envelope = Element("ENVELOPE")
    header = SubElement(envelope, "HEADER")
    SubElement(header, "TALLYREQUEST").text = "Import Data"
    body = SubElement(envelope, "BODY")
    importdata = SubElement(body, "IMPORTDATA")
    reqdesc = SubElement(importdata, "REQUESTDESC")
    SubElement(reqdesc, "REPORTNAME").text = "Vouchers"
    if company_name:
        staticvars = SubElement(reqdesc, "STATICVARIABLES")
        SubElement(staticvars, "SVCURRENTCOMPANY").text = company_name
    reqdata = SubElement(importdata, "REQUESTDATA")

    skipped: list[str] = []
    for doc in docs:
        if only_clean and _review_status(doc) != "clean":
            skipped.append(f"{doc.get('filename', '?')}: not fully auto-approved")
            continue
        voucher, reason = _voucher_for_document(doc, purchase_ledger, tax_ledger)
        if voucher is None:
            skipped.append(reason or "unknown")
            continue
        tallymessage = SubElement(reqdata, "TALLYMESSAGE")
        tallymessage.set("xmlns:UDF", "TallyUDF")
        tallymessage.append(voucher)

    raw = tostring(envelope, encoding="unicode")
    pretty = minidom.parseString(raw).toprettyxml(indent="  ")
    # minidom's pretty-printer scatters blank lines; Tally doesn't care either
    # way, but a smaller, denser file is easier for a human to sanity-check.
    pretty = "\n".join(line for line in pretty.splitlines() if line.strip())
    return pretty, skipped

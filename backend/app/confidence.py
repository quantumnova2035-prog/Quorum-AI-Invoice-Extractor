"""Confidence scoring - the part that makes this useful in a real office.

Three independent signals, combined:

  1. self-reported  - the model's own confidence per field. Free, but never
                      trustworthy on its own; models are cheerfully overconfident.
  2. agreement      - the same document extracted twice at temperature 0.3. Same
                      answer twice = stable. Different = the model was guessing.
  3. rules          - deterministic validation: GSTIN checksum, date parses,
                      line items sum to the total, tax arithmetic is consistent.

Rules are by far the strongest signal. If the line items don't sum to the total,
something is wrong - guaranteed, no model opinion required. That's why it carries
the heaviest weight.

  final = 0.30*self + 0.30*agreement + 0.40*rules
"""
from __future__ import annotations
import re
from datetime import date, datetime
from typing import Any, Optional

from dateutil import parser as dateparser

from . import config
from .schemas import FieldResult, InvoiceFields, LineItem

SCALAR_FIELDS = [
    "vendor_name", "vendor_gstin", "vendor_address",
    "buyer_name", "buyer_gstin",
    "invoice_number", "invoice_date", "due_date",
    "currency", "subtotal", "tax_amount", "total_amount",
]

# 2 state digits, 5 PAN letters, 4 digits, 1 letter, 1 entity char, 'Z', 1 checksum
GSTIN_RE = re.compile(r"^[0-3][0-9][A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
INVOICE_NO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-/_\. ]{1,30}$")


# ---------------------------------------------------------------- normalization
def normalize_value(name: str, value: Any) -> Any:
    if value is None:
        return None
    if name in ("invoice_date", "due_date"):
        return _normalize_date(value)
    if name in ("subtotal", "tax_amount", "total_amount"):
        return _normalize_money(value)
    if name in ("vendor_gstin", "buyer_gstin"):
        return re.sub(r"[^A-Z0-9]", "", str(value).upper()) or None
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip() or None
    return value


def _normalize_date(value: Any) -> Optional[str]:
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    s = str(value).strip()
    if not s:
        return None
    # Indian invoices are overwhelmingly DD/MM/YYYY, so day comes first.
    for dayfirst in (True, False):
        try:
            return dateparser.parse(s, dayfirst=dayfirst).strftime("%Y-%m-%d")
        except (ValueError, OverflowError, TypeError):
            continue
    return s


def _normalize_money(value: Any) -> Optional[float]:
    """Parse the money formats invoices actually use.

    "Rs. 1,24,500.00/-", "(1,234.50)", "INR 2114.93", "1.234,50" all have to land
    on a float. Note the trailing "/-" on Indian invoices is a currency suffix,
    not a minus sign - reading it as one silently negates the amount.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)

    s = str(value).strip()
    if not s:
        return None

    # Accounting convention: parentheses mean negative.
    negative = s.startswith("(") and s.endswith(")")
    # A minus only counts as one if it leads the number, not if it trails as "/-".
    if re.match(r"^\s*-\s*[\d(]", s):
        negative = True

    digits = re.sub(r"[^\d.,]", "", s)
    if not digits:
        return None

    # European style "1.234,50" - comma is the decimal separator.
    if "," in digits and "." in digits and digits.rfind(",") > digits.rfind("."):
        digits = digits.replace(".", "").replace(",", ".")
    else:
        digits = digits.replace(",", "")

    # Multiple stray dots ("1.234.567") - keep the last as the decimal point.
    if digits.count(".") > 1:
        head, _, tail = digits.rpartition(".")
        digits = head.replace(".", "") + "." + tail

    if digits in ("", "."):
        return None
    try:
        v = round(float(digits), 2)
    except ValueError:
        return None
    return -v if negative else v


# ---------------------------------------------------------------- signal 3: rules
def _gstin_checksum_ok(gstin: str) -> bool:
    """GSTIN carries a mod-36 check digit. This catches OCR digit swaps that a
    regex alone waves straight through."""
    if len(gstin) != 15:
        return False
    total = 0
    for i, ch in enumerate(gstin[:14]):
        if ch not in GSTIN_CHARS:
            return False
        v = GSTIN_CHARS.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return GSTIN_CHARS[(36 - total % 36) % 36] == gstin[14]


def rule_score(name: str, value: Any, fields: InvoiceFields) -> tuple[float, list[str]]:
    """Return (0..1, notes). 0.5 means 'no rule applies, stay neutral'."""
    if value is None or value == "":
        return 0.0, ["Field is missing."]

    if name in ("vendor_gstin", "buyer_gstin"):
        g = str(value)
        if not GSTIN_RE.match(g):
            return 0.05, ["GSTIN does not match the 15-character GSTIN format."]
        if not _gstin_checksum_ok(g):
            return 0.25, ["GSTIN format is right but the check digit fails."]
        return 1.0, ["GSTIN format and check digit both valid."]

    if name in ("invoice_date", "due_date"):
        try:
            d = datetime.strptime(str(value), "%Y-%m-%d").date()
        except ValueError:
            return 0.05, ["Date could not be parsed into a real calendar date."]
        today = date.today()
        if d.year < 2000:
            return 0.20, [f"Year {d.year} is implausibly old."]

        notes = []
        score = 1.0
        if d > today:
            if name == "due_date":
                notes.append("Due date parses and is in the future, as expected.")
            else:
                score, notes = 0.30, ["Invoice date is in the future - suspicious."]

        # Both day and month <=12 means DD/MM and MM/DD both parse to real dates -
        # e.g. 03/08 could be 3-Aug or 8-Mar. dateparser has to guess, and the
        # rule engine has no way to tell a correct guess from a swapped one. This
        # is the single biggest source of errors that otherwise slip through at
        # high confidence (see README error analysis) - flag it for review
        # instead of asserting false certainty.
        if d.day <= 12 and d.month <= 12 and d.day != d.month:
            score = min(score, 0.55)
            notes.append(
                f"Day and month are both ≤ 12 ({d.day:02d}/{d.month:02d}) - "
                "day/month order is ambiguous and cannot be verified from the date alone.")
        elif not notes:
            notes.append("Date parses to a plausible, unambiguous calendar date.")
        return score, notes

    if name == "total_amount":
        return _total_rules(value, fields)

    if name == "subtotal":
        return _subtotal_rules(value, fields)

    if name == "tax_amount":
        v = float(value)
        if v < 0:
            return 0.05, ["Tax amount is negative."]
        total = fields.total_amount
        if total:
            ratio = v / total if total else 0
            if ratio > 0.45:
                return 0.25, [f"Tax is {ratio:.0%} of the total - far above any GST slab."]
            return 1.0, [f"Tax is {ratio:.0%} of the total - within a plausible GST range."]
        return 0.5, ["No total available to sanity-check tax against."]

    if name == "invoice_number":
        s = str(value)
        if not INVOICE_NO_RE.match(s):
            return 0.2, ["Invoice number contains unexpected characters."]
        if not any(c.isdigit() for c in s):
            return 0.4, ["Invoice number has no digits - unusual."]
        return 1.0, ["Invoice number has a plausible format."]

    if name == "currency":
        ok = str(value).upper() in {"INR", "USD", "EUR", "GBP", "AED", "SGD", "JPY", "AUD", "CAD"}
        return (1.0, ["Recognised currency code."]) if ok else (0.3, ["Unrecognised currency code."])

    if name in ("vendor_name", "buyer_name"):
        s = str(value)
        if len(s) < 3:
            return 0.2, ["Name is implausibly short."]
        if len(s) > 120:
            return 0.35, ["Name is very long - likely captured surrounding text too."]
        return 0.85, ["Name length is plausible."]

    if name == "vendor_address":
        return (0.8, ["Address looks substantive."]) if len(str(value)) > 15 \
            else (0.35, ["Address is very short - probably truncated."])

    return 0.5, []


def _line_items_sum(items: list[LineItem]) -> Optional[float]:
    amounts = [i.amount for i in items if i.amount is not None]
    return round(sum(amounts), 2) if amounts else None


def _total_rules(value: Any, fields: InvoiceFields) -> tuple[float, list[str]]:
    """The single strongest check in the whole system: does the arithmetic close?"""
    total = float(value)
    notes: list[str] = []
    if total <= 0:
        return 0.05, ["Total is zero or negative."]

    sub, tax = fields.subtotal, fields.tax_amount
    if sub is not None and tax is not None:
        diff = abs((sub + tax) - total)
        tol = max(1.0, total * 0.01)
        if diff <= tol:
            notes.append(f"subtotal + tax = total (off by {diff:.2f}).")
            return 1.0, notes
        notes.append(f"subtotal + tax = {sub + tax:.2f} but total says {total:.2f} "
                     f"- off by {diff:.2f}.")
        return 0.10, notes

    li_sum = _line_items_sum(fields.line_items)
    if li_sum is not None:
        tol = max(1.0, total * 0.02)
        if abs(li_sum - total) <= tol:
            notes.append(f"Line items sum to the total ({li_sum:.2f}).")
            return 1.0, notes
        if sub is not None and abs(li_sum - sub) <= max(1.0, sub * 0.02):
            notes.append(f"Line items sum to the subtotal ({li_sum:.2f}); total includes tax.")
            return 0.95, notes
        notes.append(f"Line items sum to {li_sum:.2f} but total says {total:.2f}.")
        return 0.15, notes

    notes.append("No subtotal, tax, or line items available to cross-check the total.")
    return 0.5, notes


def _subtotal_rules(value: Any, fields: InvoiceFields) -> tuple[float, list[str]]:
    sub = float(value)
    if sub <= 0:
        return 0.05, ["Subtotal is zero or negative."]
    if fields.total_amount is not None and sub > fields.total_amount * 1.02:
        return 0.10, ["Subtotal is larger than the total."]
    li_sum = _line_items_sum(fields.line_items)
    if li_sum is not None:
        if abs(li_sum - sub) <= max(1.0, sub * 0.02):
            return 1.0, [f"Line items sum to the subtotal ({li_sum:.2f})."]
        return 0.20, [f"Line items sum to {li_sum:.2f}, not the stated subtotal {sub:.2f}."]
    return 0.6, ["Subtotal is plausible but nothing to cross-check it against."]


# ---------------------------------------------------------------- signal 2: agreement
def agreement_score(name: str, values: list[Any]) -> float:
    """How stable was this field across independent extraction passes?"""
    present = [v for v in values if v is not None]
    if len(values) < 2:
        return 0.5                                  # only one pass - no information
    if not present:
        return 1.0
    if len(present) < len(values):
        return 0.35                                 # one pass found it, another didn't

    if name in ("subtotal", "tax_amount", "total_amount"):
        nums = [float(v) for v in present]
        lo, hi = min(nums), max(nums)
        if hi == 0:
            return 1.0
        rel = (hi - lo) / max(abs(hi), 1e-9)
        return max(0.0, 1.0 - rel * 20)             # 5% apart -> 0

    strs = [re.sub(r"\s+", " ", str(v)).strip().lower() for v in present]
    if len(set(strs)) == 1:
        return 1.0
    return _best_pair_similarity(strs)


def _best_pair_similarity(strs: list[str]) -> float:
    from difflib import SequenceMatcher
    best = 0.0
    for i in range(len(strs)):
        for j in range(i + 1, len(strs)):
            best = max(best, SequenceMatcher(None, strs[i], strs[j]).ratio())
    return best


# ---------------------------------------------------------------- combine
def status_for(conf: float) -> str:
    if conf >= config.AUTO_ACCEPT_THRESHOLD:
        return "auto_accept"
    if conf >= config.REVIEW_THRESHOLD:
        return "review"
    return "reject"


def score_fields(passes: list[InvoiceFields],
                 self_reported: list[dict[str, float]]) -> list[FieldResult]:
    """Blend the three signals into one score per field."""
    primary = passes[0]
    results: list[FieldResult] = []

    for name in SCALAR_FIELDS:
        values = [getattr(p, name, None) for p in passes]
        value = values[0]

        self_conf = _mean([sr.get(name) for sr in self_reported if sr.get(name) is not None])
        agree = agreement_score(name, values)
        rules, notes = rule_score(name, value, primary)

        final = (config.W_SELF_REPORTED * self_conf
                 + config.W_AGREEMENT * agree
                 + config.W_RULES * rules)

        # A hard rule failure is decisive - never let a confident-sounding model
        # drag a field that failed arithmetic back above the auto-accept line.
        if rules <= 0.25:
            final = min(final, 0.45)
        if value is None:
            final, notes = 0.0, notes or ["Field is missing."]

        results.append(FieldResult(
            name=name, value=value, confidence=round(final, 3),
            status=status_for(final),
            self_reported=round(self_conf, 3), agreement=round(agree, 3),
            rules=round(rules, 3), rule_notes=notes,
        ))
    return results


def _mean(xs: list[Any]) -> float:
    vals = [float(x) for x in xs if x is not None]
    if not vals:
        return 0.5          # model said nothing - stay neutral, don't punish
    return sum(vals) / len(vals)

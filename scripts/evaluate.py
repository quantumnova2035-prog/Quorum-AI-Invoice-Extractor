"""Evaluation harness - turns the pipeline into a number.

Runs the full extractor over a labelled set and reports the three things a hiring
manager actually reads:

  1. field-level accuracy
  2. what fraction of fields were auto-approved with no human
  3. ERRORS THAT SLIPPED PAST THE CONFIDENCE FILTER  <- the number that matters

(3) is the whole point. A confidence score is only worth anything if it catches
your actual mistakes. High accuracy with a leaky filter is worse than lower
accuracy that knows when to ask a human.

    python scripts/evaluate.py --dir data/synthetic --limit 30
    python scripts/evaluate.py --dir data/synthetic --limit 30 --tune
"""
from __future__ import annotations
import argparse, asyncio, json, sys, time
from collections import defaultdict
from pathlib import Path

# Windows consoles default to cp1252 and choke on the rupee sign.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import config, confidence, parsing            # noqa: E402
from app.extraction import extract                     # noqa: E402
from app.llm_router import AllProvidersFailed, available_providers  # noqa: E402

COMPARE_FIELDS = [
    "vendor_name", "vendor_gstin", "buyer_name", "buyer_gstin",
    "invoice_number", "invoice_date", "due_date", "currency",
    "subtotal", "tax_amount", "total_amount",
]
MONEY = {"subtotal", "tax_amount", "total_amount"}


def matches(field: str, predicted, truth) -> bool:
    if predicted is None and truth is None:
        return True
    if predicted is None or truth is None:
        return False
    if field in MONEY:
        return abs(float(predicted) - float(truth)) <= max(0.5, abs(float(truth)) * 0.005)
    a, b = str(predicted).strip().lower(), str(truth).strip().lower()
    if a == b:
        return True
    # Names: tolerate punctuation/suffix noise ("Pvt Ltd." vs "Pvt Ltd").
    if field in ("vendor_name", "buyer_name"):
        norm = lambda s: "".join(ch for ch in s if ch.isalnum())
        return norm(a) == norm(b)
    return False


async def run_one(pdf: Path, truth: dict, semaphore: asyncio.Semaphore) -> dict | None:
    async with semaphore:
        doc = parsing.parse(pdf.read_bytes(), pdf.name)
        try:
            result = await extract(doc, pdf.name)
        except AllProvidersFailed as e:
            print(f"  {pdf.name}: FAILED - {e}")
            return None

    by_name = {f.name: f for f in result.fields}
    rows = []
    for name in COMPARE_FIELDS:
        f = by_name.get(name)
        expected = truth.get(name)
        rows.append({
            "file": pdf.name, "field": name,
            "predicted": f.value if f else None, "expected": expected,
            "correct": matches(name, f.value if f else None, expected),
            "confidence": f.confidence if f else 0.0,
            "status": f.status if f else "reject",
            "self_reported": f.self_reported if f else 0.0,
            "agreement": f.agreement if f else 0.0,
            "rules": f.rules if f else 0.0,
        })
    print(f"  {pdf.name}: {sum(r['correct'] for r in rows)}/{len(rows)} correct "
          f"| auto-accept {result.auto_accept_rate:.0%} | via {result.provider}")
    return {"file": pdf.name, "rows": rows, "warnings": result.warnings}


def report(rows: list[dict], threshold: float) -> dict:
    total = len(rows)
    correct = sum(r["correct"] for r in rows)
    auto = [r for r in rows if r["confidence"] >= threshold]
    escaped = [r for r in auto if not r["correct"]]
    flagged = [r for r in rows if r["confidence"] < threshold]
    caught = [r for r in flagged if not r["correct"]]
    wrong = total - correct

    per_field = defaultdict(lambda: {"n": 0, "correct": 0, "auto": 0, "escaped": 0})
    for r in rows:
        pf = per_field[r["field"]]
        pf["n"] += 1
        pf["correct"] += r["correct"]
        if r["confidence"] >= threshold:
            pf["auto"] += 1
            if not r["correct"]:
                pf["escaped"] += 1

    return {
        "threshold": threshold,
        "fields_evaluated": total,
        "field_accuracy": correct / total if total else 0.0,
        "auto_approved_rate": len(auto) / total if total else 0.0,
        "escaped_error_rate": len(escaped) / total if total else 0.0,
        "escaped_errors": len(escaped),
        "human_review_rate": len(flagged) / total if total else 0.0,
        "error_catch_rate": len(caught) / wrong if wrong else 1.0,
        "per_field": {k: dict(v) for k, v in per_field.items()},
        "escaped_examples": [
            {"file": r["file"], "field": r["field"], "predicted": r["predicted"],
             "expected": r["expected"], "confidence": r["confidence"]}
            for r in escaped[:15]
        ],
    }


def print_report(rep: dict):
    print("\n" + "=" * 74)
    print(f"RESULTS  (auto-accept threshold {rep['threshold']:.2f}, "
          f"{rep['fields_evaluated']} field predictions)")
    print("=" * 74)
    print(f"  Field-level accuracy            {rep['field_accuracy']:6.1%}")
    print(f"  Auto-approved (no human)        {rep['auto_approved_rate']:6.1%}")
    print(f"  Sent to human review            {rep['human_review_rate']:6.1%}")
    print(f"  Errors caught by the filter     {rep['error_catch_rate']:6.1%}")
    print(f"  ERRORS THAT SLIPPED PAST        {rep['escaped_error_rate']:6.1%}"
          f"   ({rep['escaped_errors']} fields)   <-- the number that matters")

    print("\n  Per field:")
    print(f"    {'field':<18}{'accuracy':>10}{'auto-appr':>11}{'escaped':>9}")
    for name, v in sorted(rep["per_field"].items(),
                          key=lambda kv: kv[1]["correct"] / max(kv[1]["n"], 1)):
        print(f"    {name:<18}{v['correct'] / v['n']:>9.0%}"
              f"{v['auto'] / v['n']:>11.0%}{v['escaped']:>9}")

    if rep["escaped_examples"]:
        print("\n  Escaped errors (auto-accepted but wrong) - the error analysis:")
        for e in rep["escaped_examples"]:
            print(f"    {e['file']} :: {e['field']} @ {e['confidence']:.2f}")
            print(f"        got      {e['predicted']!r}")
            print(f"        expected {e['expected']!r}")
    else:
        print("\n  No errors escaped the confidence filter on this run.")
    print()


def tune(rows: list[dict]):
    """Sweep the auto-accept threshold. The right threshold is a business
    decision - how much review effort buys how much safety - so show the curve
    rather than picking one silently."""
    print("\n  Threshold sweep:")
    print(f"    {'thresh':>7}{'auto-appr':>11}{'escaped':>9}{'review':>9}")
    for t in [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]:
        r = report(rows, t)
        print(f"    {t:>7.2f}{r['auto_approved_rate']:>11.1%}"
              f"{r['escaped_error_rate']:>9.1%}{r['human_review_rate']:>9.1%}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/synthetic")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--concurrency", type=int, default=3,
                    help="Keep this low - free LLM tiers rate-limit aggressively.")
    ap.add_argument("--tune", action="store_true", help="Sweep the auto-accept threshold.")
    ap.add_argument("--out", default="data/eval_report.json")
    args = ap.parse_args()

    if not available_providers():
        print("No LLM provider configured. Add OPENROUTER_API_KEY to backend/.env.")
        return 1

    base = ROOT / args.dir
    truth = json.loads((base / "ground_truth.json").read_text(encoding="utf-8"))
    pdfs = sorted((base / "pdf").glob("*.pdf"))[:args.limit]
    print(f"Evaluating {len(pdfs)} invoices via {', '.join(available_providers())} "
          f"({config.EXTRACTION_PASSES} passes each)...\n")

    t0 = time.time()
    sem = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(*[run_one(p, truth[p.name], sem) for p in pdfs])
    results = [r for r in results if r]

    rows = [row for r in results for row in r["rows"]]
    if not rows:
        print("Nothing evaluated - every document failed.")
        return 1

    rep = report(rows, config.AUTO_ACCEPT_THRESHOLD)
    rep["documents"] = len(results)
    rep["seconds"] = round(time.time() - t0, 1)
    print_report(rep)
    print(f"  {len(results)} documents in {rep['seconds']}s "
          f"({rep['seconds'] / len(results):.1f}s each)")

    if args.tune:
        tune(rows)

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": rep, "rows": rows}, indent=2, ensure_ascii=False,
                              default=str), encoding="utf-8")
    print(f"\n  Full report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""End-to-end smoke test with a stubbed LLM - no API key, no network, no cost.

Proves the whole path works: upload -> parse -> N passes -> normalize -> score ->
API response. Also asserts the behaviour that actually matters, that a wrong
value which fails an arithmetic rule does NOT get auto-accepted.

    python scripts/smoke_test.py
"""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
from unittest.mock import patch

# Windows consoles default to cp1252 and choke on the rupee sign.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import parsing                      # noqa: E402
from app.extraction import extract           # noqa: E402
from app.llm_router import LLMCall            # noqa: E402

GT = json.loads((ROOT / "data/synthetic/ground_truth.json").read_text(encoding="utf-8"))


def stub(truth: dict, corrupt: str | None = None, jitter: bool = False, wrap_in_list: bool = False):
    """Fake the LLM. `corrupt` breaks one field so we can check the filter catches it."""
    calls = {"n": 0}

    async def fake_complete_json(system, user, temperature=0.3, images=None,
                                 attempts_per_provider=2):
        calls["n"] += 1
        out = {k: truth[k] for k in
               ["vendor_name", "vendor_gstin", "vendor_address", "buyer_name",
                "buyer_gstin", "invoice_number", "invoice_date", "due_date",
                "currency", "subtotal", "tax_amount", "total_amount"]}
        out["line_items"] = truth["line_items"]
        out["confidence"] = {k: 0.97 for k in out if k != "line_items"}

        # Models return money and dates in messy formats regardless of the prompt.
        out["total_amount"] = f"Rs. {out['total_amount']:,.2f}/-"
        out["invoice_date"] = "/".join(reversed(out["invoice_date"].split("-")))

        if corrupt:
            out[corrupt] = 999999.0 if "amount" in corrupt or corrupt == "subtotal" else "GARBAGE"
        if jitter and calls["n"] % 2 == 0:
            # Second pass disagrees - the agreement signal should notice.
            out["vendor_name"] = str(out["vendor_name"])[:-4] + "Limited"
        if wrap_in_list:
            # Models occasionally return a JSON array instead of the requested
            # object. This must degrade to a low-confidence pass, not crash it.
            out = [out]
        # Latency is faked as a fixed non-zero value so the timing assertions
        # test the plumbing rather than how fast this machine happens to be.
        return LLMCall(data=out, provider="stub-provider", model="stub-model",
                       latency_ms=120.0, attempts=1,
                       prompt_tokens=1000, completion_tokens=200,
                       cost_usd=0.0)

    return patch("app.extraction.complete_json", side_effect=fake_complete_json), calls


async def run(name: str, corrupt=None, jitter=False, wrap_in_list=False):
    pdf = ROOT / "data/synthetic/pdf" / name
    doc = parsing.parse(pdf.read_bytes(), name)
    patcher, calls = stub(GT[name], corrupt, jitter, wrap_in_list)
    with patcher:
        return await extract(doc, name), calls["n"]


def show(title, result):
    print(f"\n--- {title} ---")
    print(f"source={result.source} provider={result.provider} "
          f"auto_accept={result.auto_accept_rate:.0%} mean_conf={result.overall_confidence:.2f}")
    for f in result.fields:
        flag = {"auto_accept": "OK  ", "review": "?   ", "reject": "BAD "}[f.status]
        print(f"  {flag}{f.name:<16}{str(f.value)[:36]:<38}{f.confidence:.2f}  "
              f"(s{f.self_reported:.2f} a{f.agreement:.2f} r{f.rules:.2f})")
    for w in result.warnings:
        print(f"  warning: {w}")


async def main():
    failures = []

    clean, n_calls = await run("invoice_000.pdf")
    show("clean extraction", clean)
    if n_calls != 2:
        failures.append(f"expected 2 LLM passes, got {n_calls}")
    total = next(f for f in clean.fields if f.name == "total_amount")
    if total.status != "auto_accept":
        failures.append(f"clean total should auto-accept, got {total.status}")
    if not isinstance(total.value, float):
        failures.append(f"'Rs. 1,24,500.00/-' should normalize to a float, got {total.value!r}")
    date = next(f for f in clean.fields if f.name == "invoice_date")
    if date.value != GT["invoice_000.pdf"]["invoice_date"]:
        failures.append(f"DD/MM/YYYY should normalize to ISO, got {date.value!r}")

    t = clean.timing
    print(f"  timing: total={t.total_ms:.0f}ms parse={t.parse_ms:.0f} llm={t.llm_ms:.0f} "
          f"score={t.scoring_ms:.0f} serial_llm={t.llm_serial_ms:.0f} calls={len(t.calls)}")
    if len(t.calls) != 2:
        failures.append(f"expected timing for 2 LLM calls, got {len(t.calls)}")
    if t.total_ms <= 0:
        failures.append("total_ms should be a real elapsed time, got 0")
    if t.llm_serial_ms != 240.0:
        failures.append(f"serial LLM time should sum both stubbed 120ms calls, "
                        f"got {t.llm_serial_ms}")
    if any(c.provider != "stub-provider" for c in t.calls):
        failures.append("timing should record which provider answered each pass")

    c = clean.cost
    print(f"  cost: ${c.total_usd:.6f} known={c.known} free={c.free} "
          f"est={c.is_estimated} tokens={c.prompt_tokens}in/{c.completion_tokens}out")
    if c.prompt_tokens != 2000 or c.completion_tokens != 400:
        failures.append(f"cost should sum tokens across both passes, got "
                        f"{c.prompt_tokens}/{c.completion_tokens}")
    if not c.free or not c.known:
        failures.append("two passes both reporting $0 should read as known and free")

    # A provider that reports no price must NOT be summed as if it were free -
    # this is the exact confusion that let a paid model look free for hours.
    from app.schemas import CallTiming as _CT
    from app.extraction import _sum_cost
    unknown = _sum_cost([_CT(pass_index=0, provider="p", model="m", cost_usd=None),
                         _CT(pass_index=1, provider="p", model="m", cost_usd=0.0)])
    if unknown.known or unknown.free:
        failures.append("a pass with no reported price must make the total unknown, "
                        f"not free - got known={unknown.known} free={unknown.free}")

    broken, _ = await run("invoice_001.pdf", corrupt="total_amount")
    show("total corrupted (should NOT auto-accept)", broken)
    bt = next(f for f in broken.fields if f.name == "total_amount")
    if bt.status == "auto_accept":
        failures.append("a total that fails the arithmetic rule was auto-accepted - "
                        "this is exactly the failure the confidence filter exists to prevent")

    bad_gstin, _ = await run("invoice_002.pdf", corrupt="vendor_gstin")
    show("GSTIN corrupted (should NOT auto-accept)", bad_gstin)
    bg = next(f for f in bad_gstin.fields if f.name == "vendor_gstin")
    if bg.status == "auto_accept":
        failures.append("an invalid GSTIN was auto-accepted")

    unstable, _ = await run("invoice_003.pdf", jitter=True)
    show("passes disagree on vendor_name (agreement should drop)", unstable)
    uv = next(f for f in unstable.fields if f.name == "vendor_name")
    if uv.agreement >= 0.99:
        failures.append(f"disagreeing passes should lower the agreement signal, got {uv.agreement}")

    listy, n_calls2 = await run("invoice_004.pdf", wrap_in_list=True)
    show("model returns a JSON array instead of an object (should degrade, not crash)", listy)
    if n_calls2 != 2 or listy.warnings:
        failures.append(f"a wrapped-in-list response should still complete both passes "
                        f"cleanly - got {n_calls2} passes, warnings={listy.warnings}")
    lv = next(f for f in listy.fields if f.name == "vendor_name")
    if lv.value != GT["invoice_004.pdf"]["vendor_name"]:
        failures.append(f"list-wrapped JSON should still unwrap to the right value, got {lv.value!r}")

    print("\n--- failure handling ---")
    for data, fname, label in [
        (b"", "empty.pdf", "empty file"),
        (b"%PDF-1.4 this is not really a pdf", "corrupt.pdf", "corrupt PDF"),
        (b"\x89PNG\r\n\x1a\n garbage", "broken.png", "broken image"),
    ]:
        doc = parsing.parse(data, fname)
        print(f"  {label:<16} usable={doc.usable}  {doc.warnings}")
        if doc.usable or not doc.warnings:
            failures.append(f"{label} should be unusable with a clear warning")

    print("\n" + "=" * 60)
    if failures:
        print("FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

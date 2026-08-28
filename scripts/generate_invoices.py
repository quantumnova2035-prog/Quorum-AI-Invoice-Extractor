"""Generate synthetic invoice PDFs with known ground truth.

You cannot report an accuracy number without labels, and hand-labelling 150
invoices takes days. This generates them with the answers already known, in four
different layouts and with deliberately messy variations, so you can measure the
pipeline at volume on day one. Hand-labelled real invoices still matter - use
these to build and tune, real ones to validate.

    python scripts/generate_invoices.py --count 60 --out data/synthetic
"""
from __future__ import annotations
import argparse, json, random, sys
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

# Windows consoles default to cp1252 and choke on the rupee sign.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

W, H = A4

VENDORS = [
    ("Sundaram Steel Pvt Ltd", "33", "Ambattur Industrial Estate, Chennai 600058"),
    ("Kaveri Packaging Solutions", "33", "SIDCO Industrial Estate, Coimbatore 641021"),
    ("Deccan Electricals & Controls", "36", "Balanagar, Hyderabad 500037"),
    ("Nirmal Chemicals LLP", "27", "MIDC Andheri East, Mumbai 400093"),
    ("Bharat Precision Tools", "29", "Peenya Industrial Area, Bengaluru 560058"),
    ("Ganga Textiles Mills Ltd", "09", "Site IV Sahibabad, Ghaziabad 201010"),
    ("Meridian Logistics India", "33", "Guindy Industrial Estate, Chennai 600032"),
    ("Anand Auto Components", "24", "GIDC Vatva, Ahmedabad 382445"),
]

BUYERS = [
    ("Velmurugan Engineering Works", "33", "Hosur Road, Krishnagiri 635109"),
    ("Coastal Fabrication Pvt Ltd", "33", "Ennore, Chennai 600057"),
    ("Sri Lakshmi Enterprises", "33", "Trichy Main Road, Madurai 625016"),
]

ITEMS = [
    ("M8 Hex Bolt 50mm", "73181500", 8.0, 22.0),
    ("Mild Steel Angle 40x40x5", "72162100", 320.0, 780.0),
    ("Corrugated Box 12x9x6", "48191010", 14.0, 38.0),
    ("PVC Insulated Cable 2.5sqmm", "85444911", 42.0, 96.0),
    ("Industrial Grease Cartridge", "27101980", 180.0, 460.0),
    ("Cotton Yarn 40s Combed", "52051200", 210.0, 340.0),
    ("SS 304 Sheet 2mm", "72193500", 1450.0, 2900.0),
    ("Freight & Handling Charges", "996511", 900.0, 4500.0),
    ("Machining Service - CNC Turning", "998873", 550.0, 1800.0),
    ("Ball Bearing 6204 ZZ", "84821011", 95.0, 240.0),
]

PAN_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_digit(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        v = GSTIN_CHARS.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return GSTIN_CHARS[(36 - total % 36) % 36]


def make_gstin(rng: random.Random, state: str) -> str:
    pan = ("".join(rng.choice(PAN_LETTERS) for _ in range(5))
           + "".join(str(rng.randint(0, 9)) for _ in range(4))
           + rng.choice(PAN_LETTERS))
    first14 = f"{state}{pan}{rng.randint(1, 9)}Z"
    return first14 + gstin_check_digit(first14)


def money(x: float) -> str:
    """Indian digit grouping: 1,24,500.00 - a real parsing hazard worth testing."""
    neg = x < 0
    s = f"{abs(x):.2f}"
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if neg else "") + whole + "." + frac


def build_invoice(rng: random.Random, idx: int) -> dict:
    vendor = rng.choice(VENDORS)
    buyer = rng.choice(BUYERS)
    inv_date = date.today() - timedelta(days=rng.randint(5, 400))
    terms = rng.choice([15, 30, 45, 60])

    n_items = rng.randint(1, 6)
    lines = []
    for desc, hsn, lo, hi in rng.sample(ITEMS, n_items):
        qty = float(rng.choice([1, 2, 5, 10, 20, 25, 50, 100, 200, 500]))
        unit = round(rng.uniform(lo, hi), 2)
        lines.append({"description": desc, "hsn_sac": hsn, "quantity": qty,
                      "unit_price": unit, "amount": round(qty * unit, 2)})

    subtotal = round(sum(l["amount"] for l in lines), 2)
    gst_rate = rng.choice([0.05, 0.12, 0.18, 0.28])
    interstate = vendor[1] != buyer[1]
    tax = round(subtotal * gst_rate, 2)
    total = round(subtotal + tax, 2)

    return {
        "vendor_name": vendor[0],
        "vendor_address": vendor[2],
        "vendor_gstin": make_gstin(rng, vendor[1]),
        "buyer_name": buyer[0],
        "buyer_address": buyer[2],
        "buyer_gstin": make_gstin(rng, buyer[1]),
        "invoice_number": rng.choice(["INV", "SI", "TAX", "GST"])
                          + f"/{inv_date.year}-{str(inv_date.year + 1)[2:]}/{1000 + idx}",
        "invoice_date": inv_date.isoformat(),
        "due_date": (inv_date + timedelta(days=terms)).isoformat(),
        "currency": "INR",
        "subtotal": subtotal,
        "tax_amount": tax,
        "total_amount": total,
        "line_items": lines,
        "_gst_rate": gst_rate,
        "_interstate": interstate,
        "_terms": terms,
    }


# ------------------------------------------------------------------ layouts
def _header(c, inv, layout):
    if layout == 0:
        c.setFillColor(colors.HexColor("#1f3a5f"))
        c.rect(0, H - 32 * mm, W, 32 * mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 17)
        c.drawString(18 * mm, H - 16 * mm, inv["vendor_name"])
        c.setFont("Helvetica", 8.5)
        c.drawString(18 * mm, H - 22 * mm, inv["vendor_address"])
        c.drawString(18 * mm, H - 27 * mm, f"GSTIN: {inv['vendor_gstin']}")
        c.setFont("Helvetica-Bold", 13)
        c.drawRightString(W - 18 * mm, H - 16 * mm, "TAX INVOICE")
        c.setFillColor(colors.black)
        return H - 42 * mm
    if layout == 1:
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(W / 2, H - 18 * mm, inv["vendor_name"].upper())
        c.setFont("Helvetica", 8)
        c.drawCentredString(W / 2, H - 23 * mm, inv["vendor_address"])
        c.drawCentredString(W / 2, H - 27 * mm, f"GSTIN {inv['vendor_gstin']}")
        c.setLineWidth(1.2)
        c.line(18 * mm, H - 30 * mm, W - 18 * mm, H - 30 * mm)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(W / 2, H - 36 * mm, "T A X   I N V O I C E")
        return H - 46 * mm
    if layout == 2:
        c.setFont("Helvetica-Bold", 15)
        c.drawString(18 * mm, H - 18 * mm, inv["vendor_name"])
        c.setFont("Helvetica", 8)
        c.drawString(18 * mm, H - 23 * mm, inv["vendor_address"])
        c.drawString(18 * mm, H - 27 * mm, f"GST Registration No.: {inv['vendor_gstin']}")
        c.setStrokeColor(colors.HexColor("#999999"))
        c.rect(18 * mm, H - 30 * mm, W - 36 * mm, 0.2 * mm, fill=1, stroke=0)
        return H - 40 * mm
    # layout 3: minimal / thermal-receipt style, no bold header block
    c.setFont("Courier-Bold", 11)
    c.drawString(18 * mm, H - 18 * mm, inv["vendor_name"])
    c.setFont("Courier", 8)
    c.drawString(18 * mm, H - 23 * mm, inv["vendor_address"])
    c.drawString(18 * mm, H - 27 * mm, f"GSTIN:{inv['vendor_gstin']}")
    return H - 38 * mm


def _meta(c, inv, y, layout):
    font = "Courier" if layout == 3 else "Helvetica"
    bold = "Courier-Bold" if layout == 3 else "Helvetica-Bold"

    # Date formats vary wildly across real invoices - vary them here too.
    d = date.fromisoformat(inv["invoice_date"])
    due = date.fromisoformat(inv["due_date"])
    fmt = [lambda x: x.strftime("%d/%m/%Y"),
           lambda x: x.strftime("%d-%b-%Y"),
           lambda x: x.strftime("%d.%m.%Y"),
           lambda x: x.strftime("%d %B %Y")][layout]

    c.setFont(bold, 9)
    c.drawString(18 * mm, y, "Invoice No:")
    c.drawString(18 * mm, y - 5 * mm, "Invoice Date:")
    c.drawString(18 * mm, y - 10 * mm, "Due Date:")
    c.setFont(font, 9)
    c.drawString(48 * mm, y, inv["invoice_number"])
    c.drawString(48 * mm, y - 5 * mm, fmt(d))
    c.drawString(48 * mm, y - 10 * mm, fmt(due))

    c.setFont(bold, 9)
    c.drawString(110 * mm, y, "Bill To:")
    c.setFont(font, 9)
    c.drawString(110 * mm, y - 5 * mm, inv["buyer_name"])
    c.setFont(font, 7.5)
    c.drawString(110 * mm, y - 9.5 * mm, inv["buyer_address"])
    c.drawString(110 * mm, y - 13.5 * mm, f"GSTIN: {inv['buyer_gstin']}")
    return y - 22 * mm


def _table(c, inv, y, layout):
    font = "Courier" if layout == 3 else "Helvetica"
    bold = "Courier-Bold" if layout == 3 else "Helvetica-Bold"
    cols = [18, 88, 108, 128, 152]

    if layout in (0, 2):
        c.setFillColor(colors.HexColor("#e8edf3"))
        c.rect(16 * mm, y - 2 * mm, W - 32 * mm, 7 * mm, fill=1, stroke=0)
        c.setFillColor(colors.black)

    c.setFont(bold, 8.5)
    for label, x, align in [("Description", cols[0], "l"), ("HSN/SAC", cols[1], "l"),
                            ("Qty", cols[2], "r"), ("Rate", cols[3], "r"),
                            ("Amount", cols[4] + 22, "r")]:
        (c.drawString if align == "l" else c.drawRightString)(x * mm, y, label)
    y -= 6 * mm
    c.setLineWidth(0.4)
    c.line(16 * mm, y + 1.5 * mm, W - 16 * mm, y + 1.5 * mm)

    c.setFont(font, 8.5)
    for li in inv["line_items"]:
        c.drawString(cols[0] * mm, y, li["description"][:42])
        c.drawString(cols[1] * mm, y, li["hsn_sac"])
        c.drawRightString(cols[2] * mm, y, f"{li['quantity']:g}")
        c.drawRightString(cols[3] * mm, y, money(li["unit_price"]))
        c.drawRightString((cols[4] + 22) * mm, y, money(li["amount"]))
        y -= 5.5 * mm

    y -= 2 * mm
    c.line(110 * mm, y + 2 * mm, W - 16 * mm, y + 2 * mm)

    rate_pct = int(inv["_gst_rate"] * 100)
    if inv["_interstate"]:
        tax_rows = [(f"IGST @ {rate_pct}%", inv["tax_amount"])]
    else:
        half = round(inv["tax_amount"] / 2, 2)
        tax_rows = [(f"CGST @ {rate_pct / 2:g}%", half),
                    (f"SGST @ {rate_pct / 2:g}%", round(inv["tax_amount"] - half, 2))]

    rows = [("Subtotal", inv["subtotal"])] + tax_rows
    c.setFont(font, 9)
    for label, val in rows:
        c.drawString(112 * mm, y, label)
        c.drawRightString((cols[4] + 22) * mm, y, money(val))
        y -= 5.5 * mm

    c.setFont(bold, 10.5)
    c.drawString(112 * mm, y - 1 * mm, "Grand Total")
    prefix = "INR " if layout in (1, 3) else "Rs. "
    c.drawRightString((cols[4] + 22) * mm, y - 1 * mm, prefix + money(inv["total_amount"]))
    return y - 12 * mm


def _footer(c, inv, y, layout):
    font = "Courier" if layout == 3 else "Helvetica"
    c.setFont(font, 7.5)
    c.setFillColor(colors.HexColor("#555555"))
    c.drawString(18 * mm, y, f"Payment terms: Net {inv['_terms']} days from invoice date.")
    c.drawString(18 * mm, y - 4 * mm,
                 "Interest @18% p.a. applies on overdue amounts. Subject to Chennai jurisdiction.")
    c.drawString(18 * mm, y - 8 * mm, "This is a computer-generated invoice.")
    c.setFillColor(colors.black)


def render(inv: dict, path: Path, layout: int, rotate: float = 0.0):
    c = canvas.Canvas(str(path), pagesize=A4)
    if rotate:
        # Simulates a phone photo taken at an angle - a realistic failure case.
        c.saveState()
        c.translate(W / 2, H / 2)
        c.rotate(rotate)
        c.translate(-W / 2, -H / 2)
    y = _header(c, inv, layout)
    y = _meta(c, inv, y, layout)
    y = _table(c, inv, y, layout)
    _footer(c, inv, y, layout)
    if rotate:
        c.restoreState()
    c.showPage()
    c.save()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=60)
    ap.add_argument("--out", default="data/synthetic")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    out = (root / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    (out / "pdf").mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    truth = {}
    for i in range(args.count):
        inv = build_invoice(rng, i)
        layout = i % 4
        # ~15% get a slight rotation, the way a scanned or photographed one would.
        rotate = rng.uniform(-2.5, 2.5) if rng.random() < 0.15 else 0.0
        name = f"invoice_{i:03d}.pdf"
        render(inv, out / "pdf" / name, layout, rotate)
        truth[name] = {k: v for k, v in inv.items() if not k.startswith("_")}
        truth[name]["_layout"] = layout
        truth[name]["_rotated"] = round(rotate, 2)

    (out / "ground_truth.json").write_text(
        json.dumps(truth, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Generated {args.count} invoices in {out / 'pdf'}")
    print(f"Ground truth: {out / 'ground_truth.json'}")


if __name__ == "__main__":
    sys.exit(main())

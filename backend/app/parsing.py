"""Document -> clean text.

Two paths:
  1. PDFs with a real text layer  -> PyMuPDF text extraction (fast, exact)
  2. Scans / photos / image PDFs  -> vision path: the page is rendered to PNG and
     handed to the LLM as an image (multimodal OCR), which beats bolting on a
     separate OCR engine and handles skewed phone photos far better.

Failure is visible, never silent: a corrupt/empty/encrypted file returns a clear
warning rather than an exception that 500s the API.
"""
from __future__ import annotations
import base64, io
from dataclasses import dataclass, field

import pymupdf as fitz
from PIL import Image

MIN_TEXT_CHARS = 120        # below this a "text" PDF is really a scan
MAX_PAGES = 15
RENDER_DPI = 170
MAX_IMAGE_EDGE = 1600


@dataclass
class ParsedDocument:
    text: str = ""
    images_b64: list[str] = field(default_factory=list)
    source: str = "text_pdf"          # text_pdf | ocr_image
    page_count: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return bool(self.text.strip()) or bool(self.images_b64)


def _encode_image(img: Image.Image) -> str:
    img = img.convert("RGB")
    if max(img.size) > MAX_IMAGE_EDGE:
        scale = MAX_IMAGE_EDGE / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def parse(data: bytes, filename: str) -> ParsedDocument:
    doc = ParsedDocument()
    if not data:
        doc.warnings.append("File is empty.")
        return doc

    name = filename.lower()
    if name.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp")):
        return _parse_image(data, doc)
    if name.endswith(".txt"):
        doc.text = data.decode("utf-8", errors="replace")
        doc.source, doc.page_count = "text_pdf", 1
        return doc
    return _parse_pdf(data, doc)


def _parse_image(data: bytes, doc: ParsedDocument) -> ParsedDocument:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:  # noqa: BLE001
        doc.warnings.append(f"Could not open image: {e}")
        return doc
    doc.images_b64 = [_encode_image(img)]
    doc.source, doc.page_count = "ocr_image", 1
    return doc


def _parse_pdf(data: bytes, doc: ParsedDocument) -> ParsedDocument:
    try:
        pdf = fitz.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001
        doc.warnings.append(f"Could not open PDF: {e}")
        return doc

    if pdf.needs_pass:
        doc.warnings.append("PDF is password-protected — cannot read it.")
        pdf.close()
        return doc

    doc.page_count = pdf.page_count
    if pdf.page_count == 0:
        doc.warnings.append("PDF has no pages.")
        pdf.close()
        return doc

    pages = min(pdf.page_count, MAX_PAGES)
    if pdf.page_count > MAX_PAGES:
        doc.warnings.append(
            f"Document has {pdf.page_count} pages; only the first {MAX_PAGES} were read.")

    chunks = [pdf[i].get_text("text") for i in range(pages)]
    text = "\n".join(chunks).strip()

    if len(text) >= MIN_TEXT_CHARS:
        doc.text, doc.source = text, "text_pdf"
    else:
        # No usable text layer — it's a scan. Render pages as images instead.
        doc.warnings.append("No text layer found; treated as a scan and read as images.")
        doc.source = "ocr_image"
        doc.text = text
        zoom = RENDER_DPI / 72
        for i in range(min(pages, 4)):
            pix = pdf[i].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            doc.images_b64.append(_encode_image(
                Image.frombytes("RGB", (pix.width, pix.height), pix.samples)))
    pdf.close()

    if not doc.usable:
        doc.warnings.append("Nothing readable was found in this document.")
    return doc

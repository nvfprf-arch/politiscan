import os
import json
import base64
import urllib.request
from io import BytesIO

from language_config import TESSERACT_CODES, STATE_PRIMARY_LANGUAGE


def fetch_article_content(url: str, state: str) -> tuple[str | None, str]:
    """Fetch and extract full article text from a URL.

    Step 1: HEAD request to determine whether the resource is a PDF or HTML.
    Step 2 (HTML): newspaper3k main-body extraction → ("html").
    Step 3 (PDF): four strategies tried in order:
        pdfplumber   → "digital_pdf"
        pytesseract  → "scanned_pdf"
        Sarvam OCR   → "sarvam_ocr"
        fallback     → (None, "failed")

    Returns:
        (text, source_type)
        text is None only when source_type is "failed".
    """
    if not url or not url.startswith("http"):
        return None, "html_fallback"

    # Step 1 ─ check whether the URL points to a PDF
    is_pdf = url.lower().rstrip("?#").endswith(".pdf")

    if not is_pdf:
        try:
            req = urllib.request.Request(
                url,
                method="HEAD",
                headers={"User-Agent": "Mozilla/5.0 (compatible; PolitiScan/1.1)"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                ct = resp.headers.get("Content-Type", "")
                is_pdf = "application/pdf" in ct
        except Exception:
            pass   # can't determine type from HEAD — assume HTML

    # Step 2 / Step 3 ─ dispatch
    if is_pdf:
        return _extract_pdf(url, state)
    return _extract_html(url)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def _extract_html(url: str) -> tuple[str | None, str]:
    """newspaper3k main-body extraction from an HTML page.
    Returns (None, "html_fallback") on any failure so the caller can use the
    original RSS snippet — HTML articles must never show Manual Review Required.
    """
    try:
        from newspaper import Article
        art = Article(url, request_timeout=10)
        art.download()
        art.parse()
        text = (art.text or "").strip()
        if len(text) > 100:
            return text[:8000], "html"
    except Exception:
        pass
    return None, "html_fallback"


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _extract_pdf(url: str, state: str) -> tuple[str | None, str]:
    """Download PDF bytes then try four extraction strategies in priority order."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PolitiScan/1.1)"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            pdf_bytes = resp.read()
    except Exception:
        return None, "failed"

    # Strategy 1 ─ pdfplumber (digital / text-layer PDFs)
    try:
        import pdfplumber
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages).strip()
        if len(text) > 100:
            return text[:8000], "digital_pdf"
    except Exception:
        pass

    # Strategy 2 ─ pdf2image + pytesseract (scanned / image PDFs)
    try:
        import pdf2image
        import pytesseract
        lang_name = STATE_PRIMARY_LANGUAGE.get(state, "English")
        tess_lang = TESSERACT_CODES.get(lang_name, "eng")
        images    = pdf2image.convert_from_bytes(pdf_bytes, dpi=200)
        text      = "\n".join(
            pytesseract.image_to_string(img, lang=tess_lang) for img in images
        ).strip()
        if len(text) > 100:
            return text[:8000], "scanned_pdf"
    except Exception:
        pass

    # Strategy 3 ─ Sarvam AI document parse
    sarvam_key = os.getenv("SARVAM_API_KEY", "")
    if sarvam_key:
        try:
            encoded = base64.b64encode(pdf_bytes).decode("ascii")
            payload = json.dumps({
                "document": encoded,
                "model":    "sarvam-ocr",
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.sarvam.ai/parse-document",
                data=payload,
                headers={
                    "Content-Type":         "application/json",
                    "api-subscription-key": sarvam_key,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = (data.get("text") or data.get("content") or "").strip()
            if text:
                return text[:8000], "sarvam_ocr"
        except Exception:
            pass

    # Strategy 4 ─ all extraction methods exhausted
    return None, "failed"

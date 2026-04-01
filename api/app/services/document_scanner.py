"""Extract text from uploaded documents and summarise with AI.

Supports PDF (pdfplumber), DOCX (python-docx), and images (OpenAI Vision).
Each document is scanned exactly once — the result is persisted in
``documents.scanned_text`` and never reprocessed.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from app.logger import get_logger
from app.services.ai_client import AIClientError, call_openai
from app.settings import settings

log = get_logger("carver.document_scanner")

_MAX_RAW_CHARS = 3000
_SKIP_DOC_TYPES = {"photo"}

_SUMMARISE_SYSTEM = (
    "You extract useful career information from yacht crew documents. "
    "Return a concise plain-text summary (max 400 words) focusing on: "
    "roles held, vessels worked on, years of experience, certifications, "
    "skills, qualifications, languages, and any other details relevant to "
    "superyacht job matching. Omit personal addresses, ID numbers, and "
    "dates of birth. If the document has no useful career content, reply "
    "with an empty string."
)

_DOC_TYPE_LABELS = {
    "cv": "CV / résumé",
    "references": "professional references letter",
    "passport": "passport or travel document",
    "stcw": "STCW certificate",
    "eng1": "ENG1 medical certificate",
}


# -- Text extraction helpers --------------------------------------------------

def _extract_pdf(file_path: Path) -> str:
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                parts.append(text)
    return "\n".join(parts)


def _extract_docx(file_path: Path) -> str:
    import docx

    doc = docx.Document(str(file_path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_image_via_vision(file_path: Path, doc_type: str) -> str:
    """Use OpenAI Vision to read text from an image (certificates, passports)."""
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
    suffix = file_path.suffix.lower()
    mime = mime_map.get(suffix, "image/jpeg")

    image_bytes = file_path.read_bytes()
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    label = _DOC_TYPE_LABELS.get(doc_type, "document")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SUMMARISE_SYSTEM},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Read this image of a yacht crew member's {label}. "
                        "Extract all career-relevant text and details visible in the image."
                    ),
                },
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]

    return call_openai(
        api_key=settings.OPENAI_API_KEY,
        messages=messages,
        model=settings.OPENAI_MODEL,
        max_tokens=600,
        temperature=0.1,
    )


def _extract_raw_text(file_path: Path, doc_type: str) -> str | None:
    """Return raw text from the file, or None if the format is unsupported."""
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        text = _extract_pdf(file_path)
        if text.strip():
            return text
        # PDF might be image-based (scanned) — fall through to vision
        log.info("PDF has no extractable text, falling back to vision | path=%s", file_path.name)
        return None

    if suffix == ".docx":
        return _extract_docx(file_path)

    if suffix in {".jpg", ".jpeg", ".png"}:
        return None  # handled by vision path

    if suffix == ".doc":
        log.info("Legacy .doc format — skipping text extraction | path=%s", file_path.name)
        return None

    return None


# -- Public API ----------------------------------------------------------------

def scan_document(file_path: Path, doc_type: str) -> str | None:
    """Extract and summarise a document. Returns the summary or None on failure.

    For images and scanned PDFs the Vision API is used directly (extraction +
    summarisation in one call).  For text-based PDFs and DOCX the raw text is
    extracted locally, then summarised via a separate AI call.
    """
    if doc_type in _SKIP_DOC_TYPES:
        return None

    if not file_path.exists():
        log.warning("File not found for scanning | path=%s", file_path)
        return None

    try:
        raw_text = _extract_raw_text(file_path, doc_type)
    except Exception:
        log.exception("Text extraction failed | path=%s | doc_type=%s", file_path.name, doc_type)
        raw_text = None

    suffix = file_path.suffix.lower()
    needs_vision = raw_text is None and suffix in {".pdf", ".jpg", ".jpeg", ".png"}

    if needs_vision:
        if not settings.OPENAI_API_KEY:
            log.warning("No OPENAI_API_KEY — cannot use vision for document scan")
            return None
        try:
            return _extract_image_via_vision(file_path, doc_type)
        except (AIClientError, RuntimeError):
            log.exception("Vision scan failed | path=%s | doc_type=%s", file_path.name, doc_type)
            return None

    if not raw_text or not raw_text.strip():
        log.info("No text extracted from document | path=%s | doc_type=%s", file_path.name, doc_type)
        return None

    # Summarise with AI
    if not settings.OPENAI_API_KEY:
        log.warning("No OPENAI_API_KEY — returning truncated raw text as fallback")
        return raw_text[:_MAX_RAW_CHARS].strip()

    truncated = raw_text[:_MAX_RAW_CHARS]
    label = _DOC_TYPE_LABELS.get(doc_type, "document")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SUMMARISE_SYSTEM},
        {"role": "user", "content": f"Here is the text from a crew member's {label}:\n\n{truncated}"},
    ]

    try:
        return call_openai(
            api_key=settings.OPENAI_API_KEY,
            messages=messages,
            model=settings.OPENAI_MODEL,
            max_tokens=600,
            temperature=0.1,
        )
    except (AIClientError, RuntimeError):
        log.exception("AI summarisation failed | doc_type=%s", doc_type)
        return raw_text[:_MAX_RAW_CHARS].strip()

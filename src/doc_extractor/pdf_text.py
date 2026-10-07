"""Pull a text layer out of a PDF. OCR is optional and off by default."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from doc_extractor.config import Settings

EMPTY_NOTE = (
    "No text layer found. This usually means the PDF is a scan or a photo. "
    "OCR is optional: install the Tesseract binary, install the ocr extra "
    "(pip install 'ai-document-extractor[ocr]'), and set OCR_ENABLED=true. "
    "The demo PDFs already have a text layer, so OCR is not required to try the project."
)


@dataclass(frozen=True)
class TextExtract:
    text: str
    status: str
    note: str = ""


def extract_pdf_text(data: bytes, settings: Settings) -> TextExtract:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        handle.write(data)
        handle.flush()
        path = handle.name
        plumber_text = _safe_pdfplumber(path)
        pypdf_text = _safe_pypdf(path)
        text = plumber_text if len(plumber_text) >= len(pypdf_text) else pypdf_text
        if not _too_short(text):
            return TextExtract(text=text, status="ok")
        if settings.ocr_enabled:
            try:
                ocr_text = _ocr(path)
            except Exception as exc:
                return TextExtract(
                    text=text,
                    status="empty",
                    note=f"{EMPTY_NOTE} OCR failed: {exc}",
                )
            if not _too_short(ocr_text):
                return TextExtract(text=ocr_text, status="ocr")
        return TextExtract(text=text, status="empty", note=EMPTY_NOTE)


def _too_short(text: str) -> bool:
    return len(text.strip()) < 20


def _safe_pdfplumber(path: str) -> str:
    try:
        import pdfplumber

        parts: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        return "\n".join(parts)
    except Exception:
        return ""


def _safe_pypdf(path: str) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(path)
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return ""


def _ocr(path: str) -> str:
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError as exc:
        raise RuntimeError(
            "OCR_ENABLED is true, but pytesseract and pdf2image are not installed."
        ) from exc
    images = convert_from_path(Path(path))
    return "\n".join(pytesseract.image_to_string(image) for image in images)

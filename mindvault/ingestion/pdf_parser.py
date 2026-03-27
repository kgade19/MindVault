"""PDF text extraction using pdfplumber."""
from __future__ import annotations

import io

import pdfplumber


def extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF byte string."""
    text_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n\n".join(text_parts)

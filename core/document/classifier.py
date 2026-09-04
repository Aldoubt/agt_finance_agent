"""Document classification abstraction.

The first version keeps rules lightweight. Vision/OCR models can be plugged in later.
"""

from pathlib import Path


def classify_document(path: str) -> str:
    ext = Path(path).suffix.lower()

    if ext == ".pdf":
        return "invoice_candidate"

    if ext in {".png", ".jpg", ".jpeg", ".webp"}:
        return "image_candidate"

    if ext == ".docx":
        return "document_candidate"

    if ext == ".xlsx":
        return "template_candidate"

    return "unknown"

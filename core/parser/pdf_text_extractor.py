from pathlib import Path

import fitz  # PyMuPDF


class PDFTextExtractor:
    """Extract text from invoice PDFs using PyMuPDF.

    OCR is intentionally not included in Phase 2. Scanned PDFs will be handled
    by a later OCR pipeline.
    """

    def extract(self, pdf_path: str) -> str:
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(path)

        pages = []
        with fitz.open(path) as doc:
            for page in doc:
                pages.append(page.get_text("text"))

        return "\n".join(pages).strip()

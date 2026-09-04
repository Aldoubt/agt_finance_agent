"""Document scanner.

Collect raw files and generate normalized document metadata.
"""

from pathlib import Path
from dataclasses import dataclass


SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".xlsx": "spreadsheet",
    ".docx": "document",
}


@dataclass
class DocumentInfo:
    path: str
    extension: str
    detected_type: str


def scan_folder(folder: str):
    """Scan input folder without assuming file names or ordering."""
    results = []
    for p in Path(folder).rglob("*"):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext in SUPPORTED_EXTENSIONS:
            results.append(
                DocumentInfo(
                    path=str(p),
                    extension=ext,
                    detected_type=SUPPORTED_EXTENSIONS[ext],
                )
            )
    return results

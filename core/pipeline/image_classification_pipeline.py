"""Batch image classification pipeline."""

import json
from collections import Counter
from pathlib import Path

from core.document.image_classifier import ImageDocumentClassifier


class ImageClassificationPipeline:
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

    def __init__(self) -> None:
        self.classifier = ImageDocumentClassifier()

    @staticmethod
    def _natural_key(path: Path):
        digits = "".join(x for x in path.stem if x.isdigit())
        return (path.stem.rstrip(digits), int(digits) if digits else 0, path.name)

    def run(self, input_dir: str | Path, output_json: str | Path | None = None) -> dict:
        root = Path(input_dir)
        images = sorted(
            [p for p in root.iterdir() if p.is_file() and p.suffix.lower() in self.IMAGE_EXTENSIONS],
            key=self._natural_key,
        )
        rows = [self.classifier.classify(path).to_dict() for path in images]
        counts = Counter(row["category"] for row in rows)
        report = {
            "image_count": len(rows),
            "counts": dict(sorted(counts.items())),
            "documents": rows,
        }

        if output_json:
            target = Path(output_json)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report


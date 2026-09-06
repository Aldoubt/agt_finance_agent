"""Lightweight visual ranking between a real product photo and order screenshots.

This deliberately avoids a heavyweight neural dependency. It uses local SIFT
features to ask a narrow question: does a product photo share distinctive local
visual structure with the product image embedded in an already-matched order
detail screenshot? The result is review evidence only, never an automatic
financial relation.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VisualEvidenceCandidate:
    invoice_file: str
    proof_file: str
    score: float
    good_matches: int
    descriptor_count: int


class OrderVisualRanker:
    def __init__(self, nfeatures: int = 1200, ratio_test: float = 0.72) -> None:
        try:
            import cv2
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise RuntimeError(
                "Lightweight visual ranking requires OpenCV. Install the OCR/vision extras first."
            ) from exc
        self.cv2 = cv2
        self.detector = cv2.SIFT_create(nfeatures=nfeatures)
        self.matcher = cv2.BFMatcher(cv2.NORM_L2)
        self.ratio_test = ratio_test
        self._cache: dict[tuple[str, str], tuple[object, int]] = {}

    def _read_gray(self, path: str | Path, mode: str):
        cv2 = self.cv2
        # cv2.imread() is unreliable with non-ASCII Windows paths. Reading the
        # bytes through NumPy and decoding them keeps Chinese workspace paths
        # working consistently.
        try:
            import numpy as np

            data = np.fromfile(str(path), dtype=np.uint8)
            image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
        except (OSError, ValueError):
            image = None
        if image is None:
            return None

        if mode == "proof":
            # The current order-detail screenshots keep the item card in the
            # upper half. Excluding the status bar and lower metadata prevents
            # text-heavy areas from dominating local features.
            height = image.shape[0]
            image = image[int(height * 0.05) : int(height * 0.58), :]

        longest = max(image.shape[:2])
        if longest > 1400:
            scale = 1400.0 / longest
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        return image

    def _features(self, path: str | Path, mode: str):
        key = (str(Path(path)), mode)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        image = self._read_gray(path, mode)
        if image is None:
            result = (None, 0)
        else:
            keypoints, descriptors = self.detector.detectAndCompute(image, None)
            result = (descriptors, len(keypoints or []))
        self._cache[key] = result
        return result

    def score(self, photo_file: str | Path, proof_file: str | Path) -> tuple[float, int, int]:
        photo_desc, photo_count = self._features(photo_file, "photo")
        proof_desc, proof_count = self._features(proof_file, "proof")
        if photo_desc is None or proof_desc is None or len(photo_desc) < 2 or len(proof_desc) < 2:
            return 0.0, 0, min(photo_count, proof_count)

        pairs = self.matcher.knnMatch(photo_desc, proof_desc, k=2)
        good = []
        for pair in pairs:
            if len(pair) != 2:
                continue
            first, second = pair
            if first.distance < self.ratio_test * second.distance:
                good.append(first)

        denominator = max(12, min(photo_count, proof_count))
        normalized = min(1.0, len(good) / denominator * 8.0)
        return round(normalized, 4), len(good), denominator

    def rank(
        self,
        photo_file: str | Path,
        proof_by_invoice: dict[str, str],
        top_k: int | None = 3,
    ) -> list[VisualEvidenceCandidate]:
        rows = []
        for invoice_file, proof_file in proof_by_invoice.items():
            score, good_matches, descriptor_count = self.score(photo_file, proof_file)
            rows.append(
                VisualEvidenceCandidate(
                    invoice_file=invoice_file,
                    proof_file=proof_file,
                    score=score,
                    good_matches=good_matches,
                    descriptor_count=descriptor_count,
                )
            )
        rows.sort(key=lambda row: (row.score, row.good_matches), reverse=True)
        return rows[:top_k] if top_k else rows


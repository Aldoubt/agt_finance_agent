"""Deterministic first-pass classifier for image documents.

The classifier deliberately separates *structural* image classification from
semantic recognition.  It can reliably distinguish ordinary product photos
from tall application screenshots without OCR or a vision model.  Screenshot
sub-types (order/payment) are left unresolved until a semantic adapter has
enough evidence.
"""

from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageStat


@dataclass
class ImageClassification:
    path: str
    category: str
    confidence: float
    width: int
    height: int
    aspect_ratio: float
    pixel_stddev: float
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


class ImageDocumentClassifier:
    """Classify images by layout/photographic statistics only."""

    def classify(self, path: str | Path) -> ImageClassification:
        image_path = Path(path)
        with Image.open(image_path) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            sample = rgb.resize((128, 128))
            stddev = sum(ImageStat.Stat(sample).stddev) / 3.0

        aspect = width / height if height else 0.0

        # Modern phone screenshots are typically very tall (roughly 9:20,
        # ratio about 0.45) and have much flatter color distributions than a
        # natural camera photo.  Requiring both conditions avoids classifying
        # an ordinary portrait photograph as a screenshot solely by shape.
        if aspect <= 0.50 and stddev <= 45.0:
            return ImageClassification(
                path=str(image_path),
                category="screenshot_unknown",
                confidence=0.95,
                width=width,
                height=height,
                aspect_ratio=round(aspect, 4),
                pixel_stddev=round(stddev, 2),
                reason="tall_phone_layout_and_flat_pixel_distribution",
            )

        # Natural photographs tend to have stronger color/texture variation.
        if stddev >= 42.0 or aspect > 0.50:
            return ImageClassification(
                path=str(image_path),
                category="product_photo_candidate",
                confidence=0.90,
                width=width,
                height=height,
                aspect_ratio=round(aspect, 4),
                pixel_stddev=round(stddev, 2),
                reason="photographic_layout_or_texture_variation",
            )

        return ImageClassification(
            path=str(image_path),
            category="unknown",
            confidence=0.40,
            width=width,
            height=height,
            aspect_ratio=round(aspect, 4),
            pixel_stddev=round(stddev, 2),
            reason="insufficient_structural_evidence",
        )


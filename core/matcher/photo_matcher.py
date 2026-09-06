"""High-confidence product-photo to invoice-item matching."""

from dataclasses import dataclass
from difflib import SequenceMatcher
import re


@dataclass
class PhotoMatch:
    photo_file: str
    invoice_file: str
    item_name: str
    score: float
    reasons: list[str]


class PhotoMatcher:
    ALIASES = {
        "magnifier": ("放大镜",),
        "solderingiron": ("电烙铁",),
        "servo": ("舵机",),
    }

    @staticmethod
    def _norm(value: str) -> str:
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (value or "").lower())

    @staticmethod
    def _model_tokens(value: str) -> list[str]:
        raw = re.findall(r"[A-Za-z][A-Za-z0-9+()./-]{3,}", value or "")
        return [re.sub(r"[^a-z0-9]", "", token.lower()) for token in raw]

    def score_item(self, ocr_text: str, item_name: str) -> tuple[float, list[str]]:
        text_norm = self._norm(ocr_text)
        item_norm = self._norm(item_name)
        reasons: list[str] = []
        score = 0.0

        item_tokens = self._model_tokens(item_name)
        ocr_tokens = self._model_tokens(ocr_text)
        best_model = 0.0
        best_pair = None
        for item_token in item_tokens:
            for ocr_token in ocr_tokens:
                ratio = SequenceMatcher(None, item_token, ocr_token).ratio()
                if item_token in ocr_token or ocr_token in item_token:
                    ratio = max(ratio, min(len(item_token), len(ocr_token)) / max(len(item_token), len(ocr_token)))
                if ratio > best_model:
                    best_model = ratio
                    best_pair = (item_token, ocr_token)
        if best_model >= 0.72 and best_pair:
            score = max(score, 0.88)
            reasons.append(f"model_token:{best_pair[0]}~{best_pair[1]}:{best_model:.2f}")

        for english, chinese_terms in self.ALIASES.items():
            if english in text_norm and any(term in item_name for term in chinese_terms):
                score = max(score, 0.86)
                reasons.append(f"alias:{english}")

        # Exact distinctive Chinese phrases are useful, but keep this below the
        # model-token threshold because OCR photos often include unrelated labels.
        chunks = [x for x in re.findall(r"[\u4e00-\u9fff]{3,}", item_name) if x not in {"电子元件", "电子元器件", "金属制品"}]
        for chunk in chunks:
            if chunk in ocr_text:
                score = max(score, 0.80)
                reasons.append(f"chinese_phrase:{chunk}")
                break

        return score, reasons

    def match(self, photo_ocr: list[tuple[str, str]], invoices, threshold: float = 0.84) -> list[PhotoMatch]:
        candidates = []
        for photo_file, text in photo_ocr:
            for invoice in invoices:
                for item in invoice.items:
                    score, reasons = self.score_item(text, item.name)
                    if score >= threshold:
                        candidates.append((score, photo_file, invoice, item, reasons))

        # Resolve strongest unique photo/item pairs greedily. A low-confidence
        # ambiguous image stays unmatched rather than being forced onto an item.
        matches: list[PhotoMatch] = []
        used_photos: set[str] = set()
        used_items: set[tuple[str, str]] = set()
        for score, photo_file, invoice, item, reasons in sorted(candidates, key=lambda x: x[0], reverse=True):
            key = (invoice.source, item.name)
            if photo_file in used_photos or key in used_items:
                continue
            used_photos.add(photo_file)
            used_items.add(key)
            matches.append(
                PhotoMatch(
                    photo_file=photo_file,
                    invoice_file=invoice.source,
                    item_name=item.name,
                    score=round(score, 4),
                    reasons=reasons,
                )
            )
        return matches


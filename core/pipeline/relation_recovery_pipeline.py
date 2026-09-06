"""Recover purchase-proof relations from unordered invoice/image inputs."""

import json
from pathlib import Path

from core.document.image_classifier import ImageDocumentClassifier
from core.matcher.purchase_proof_matcher import PurchaseProofMatcher
from core.matcher.photo_matcher import PhotoMatcher
from core.parser.invoice_parser import InvoiceParser
from core.parser.screenshot_parser import ScreenshotParser


class RelationRecoveryPipeline:
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

    def __init__(self) -> None:
        self.image_classifier = ImageDocumentClassifier()
        self.invoice_parser = InvoiceParser()
        self.screenshot_parser = ScreenshotParser()
        self.proof_matcher = PurchaseProofMatcher()
        self.photo_matcher = PhotoMatcher()

    @staticmethod
    def _summary_proof(proof) -> dict:
        return {
            "source_file": proof.source_file,
            "category": proof.category,
            "confidence": proof.confidence,
            "amount": proof.amount,
            "order_no": proof.order_no,
            "payment_trade_no": proof.payment_trade_no,
            "payment_time": proof.payment_time,
            "merchant": proof.merchant,
        }

    def run(self, input_dir: str | Path, output_json: str | Path | None = None) -> dict:
        root = Path(input_dir)
        invoices = [self.invoice_parser.parse(str(p)) for p in sorted(root.glob("*.pdf"))]

        image_rows = []
        screenshot_paths = []
        photo_paths = []
        for path in sorted(root.iterdir()):
            if not path.is_file() or path.suffix.lower() not in self.IMAGE_EXTENSIONS:
                continue
            classified = self.image_classifier.classify(path)
            image_rows.append(classified.to_dict())
            if classified.category == "screenshot_unknown":
                screenshot_paths.append(path)
            elif classified.category == "product_photo_candidate":
                photo_paths.append(path)

        proofs = [self.screenshot_parser.parse(path) for path in screenshot_paths]
        purchase_proofs = [p for p in proofs if p.category == "purchase_proof"]
        payment_proofs = [p for p in proofs if p.category == "payment_proof"]
        matches = self.proof_matcher.match(purchase_proofs, invoices)
        photo_ocr = []
        for path in photo_paths:
            parsed_photo = self.screenshot_parser.parse(path)
            photo_ocr.append((str(path), parsed_photo.text))
        photo_matches = self.photo_matcher.match(photo_ocr, invoices)
        matched_proofs = {m.screenshot_file for m in matches}
        matched_invoices = {m.invoice_file for m in matches}

        report = {
            "invoice_count": len(invoices),
            "image_count": len(image_rows),
            "product_photo_candidate_count": len(photo_paths),
            "screenshot_count": len(screenshot_paths),
            "purchase_proof_count": len(purchase_proofs),
            "payment_proof_count": len(payment_proofs),
            "matched_purchase_proof_count": len(matches),
            "matched_photo_count": len(photo_matches),
            "unmatched_purchase_proofs": [
                p.source_file for p in purchase_proofs if p.source_file not in matched_proofs
            ],
            "unmatched_invoices": [
                i.source for i in invoices if i.source not in matched_invoices
            ],
            "images": image_rows,
            "proofs": [self._summary_proof(p) for p in proofs],
            "purchase_proof_matches": [
                {
                    "screenshot_file": m.screenshot_file,
                    "invoice_file": m.invoice_file,
                    "score": m.score,
                    "reasons": m.reasons,
                }
                for m in matches
            ],
            "photo_matches": [
                {
                    "photo_file": m.photo_file,
                    "invoice_file": m.invoice_file,
                    "item_name": m.item_name,
                    "score": m.score,
                    "reasons": m.reasons,
                }
                for m in photo_matches
            ],
        }

        if output_json:
            target = Path(output_json)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    @staticmethod
    def purchase_proof_map(report: dict) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = {}
        for match in report.get("purchase_proof_matches", []):
            mapping.setdefault(match["invoice_file"], []).append(match["screenshot_file"])
        return mapping

    @staticmethod
    def photo_map(report: dict) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = {}
        for match in report.get("photo_matches", []):
            key = f'{match["invoice_file"]}::{match["item_name"]}'
            mapping.setdefault(key, []).append(match["photo_file"])
        return mapping


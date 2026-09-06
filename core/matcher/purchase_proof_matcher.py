"""Match parsed purchase-proof screenshots to parsed invoices."""

from dataclasses import dataclass
import re


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", (value or "").lower())


@dataclass
class PurchaseProofMatch:
    screenshot_file: str
    invoice_file: str
    score: float
    reasons: list[str]


class PurchaseProofMatcher:
    def score(self, proof, invoice) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        if proof.amount is not None and abs(float(proof.amount) - float(invoice.total or 0)) < 0.01:
            score += 0.70
            reasons.append("exact_amount")

        proof_text = _norm(proof.text)
        item_hits = 0
        for item in invoice.items:
            name = _norm(item.name)
            if name and (name in proof_text or any(name[i : i + 4] in proof_text for i in range(max(1, len(name) - 3)))):
                item_hits += 1
        if invoice.items and item_hits:
            ratio = item_hits / len(invoice.items)
            score += 0.20 * ratio
            reasons.append(f"item_text:{item_hits}/{len(invoice.items)}")

        invoice_order_no = getattr(invoice, "order_no", "")
        if proof.order_no and invoice_order_no and proof.order_no == invoice_order_no:
            score += 0.20
            reasons.append("exact_order_no")

        return min(score, 1.0), reasons

    def match(self, proofs, invoices, threshold: float = 0.70) -> list[PurchaseProofMatch]:
        matches: list[PurchaseProofMatch] = []
        used_invoices: set[str] = set()
        used_proofs: set[str] = set()
        for proof in proofs:
            candidates = []
            for invoice in invoices:
                if invoice.source in used_invoices:
                    continue
                score, reasons = self.score(proof, invoice)
                candidates.append((score, invoice, reasons))
            if not candidates:
                continue
            score, invoice, reasons = max(candidates, key=lambda x: x[0])
            if score >= threshold:
                used_invoices.add(invoice.source)
                used_proofs.add(proof.source_file)
                matches.append(
                    PurchaseProofMatch(
                        screenshot_file=proof.source_file,
                        invoice_file=invoice.source,
                        score=round(score, 4),
                        reasons=reasons,
                    )
                )

        # Conservative residual resolution: if the high-confidence phase leaves
        # exactly one proof and one invoice, and there is at least some item-text
        # evidence, the one-to-one remainder itself is useful evidence. This
        # handles OCR cases where the displayed amount glyph was missed.
        remaining_proofs = [p for p in proofs if p.source_file not in used_proofs]
        remaining_invoices = [i for i in invoices if i.source not in used_invoices]
        if len(remaining_proofs) == 1 and len(remaining_invoices) == 1:
            proof = remaining_proofs[0]
            invoice = remaining_invoices[0]
            score, reasons = self.score(proof, invoice)
            if any(reason.startswith("item_text:") for reason in reasons):
                matches.append(
                    PurchaseProofMatch(
                        screenshot_file=proof.source_file,
                        invoice_file=invoice.source,
                        score=round(max(score, 0.75), 4),
                        reasons=reasons + ["unique_remainder"],
                    )
                )
        return matches


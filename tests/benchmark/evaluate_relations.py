"""Evaluate image classification and relation recovery against manual truth."""

import json
from pathlib import Path
import re

from core.parser.invoice_parser import InvoiceParser


def _image_number(name: str) -> int | None:
    match = re.search(r"(\d+)", Path(name).stem)
    return int(match.group(1)) if match else None


def _heading_amount(heading: str) -> float | None:
    match = re.search(r"--\s*([0-9]+(?:\.[0-9]+)?)", heading or "")
    return float(match.group(1)) if match else None


def evaluate(
    ground_truth_json: str | Path,
    relation_report_json: str | Path,
    invoice_dir: str | Path,
) -> dict:
    truth = json.loads(Path(ground_truth_json).read_text(encoding="utf-8"))
    relation = json.loads(Path(relation_report_json).read_text(encoding="utf-8"))

    parser = InvoiceParser()
    invoices = [parser.parse(str(path)) for path in sorted(Path(invoice_dir).glob("*.pdf"))]
    amount_to_invoice = {round(float(inv.total), 2): Path(inv.source).name for inv in invoices}

    # Manual DOCX: product-photo section maps original images 1..15 to the
    # named/amounted product groups. Images 16..30 are transaction screenshots.
    photo_truth = {}
    for row in truth.get("photo_truth", []):
        source_image = row.get("source_image")
        if not source_image:
            continue
        number = _image_number(source_image)
        amount = _heading_amount(row.get("heading", ""))
        if number is None or number > 15 or amount is None:
            continue
        invoice_name = amount_to_invoice.get(round(amount, 2))
        if invoice_name:
            photo_truth[source_image] = invoice_name

    all_images = {
        Path(row["path"]).name: row["category"]
        for row in relation.get("images", [])
    }
    structural_correct = 0
    structural_total = 0
    for image_name, predicted in all_images.items():
        number = _image_number(image_name)
        if number is None:
            continue
        expected = "product_photo_candidate" if number <= 15 else "screenshot_unknown"
        structural_total += 1
        structural_correct += int(predicted == expected)

    predicted_photo = {
        Path(row["photo_file"]).name: Path(row["invoice_file"]).name
        for row in relation.get("photo_matches", [])
    }
    photo_correct = sum(
        1 for image_name, invoice_name in predicted_photo.items()
        if photo_truth.get(image_name) == invoice_name
    )
    photo_precision = photo_correct / len(predicted_photo) if predicted_photo else None
    photo_recall = photo_correct / len(photo_truth) if photo_truth else None
    if photo_precision is not None and photo_recall is not None and photo_precision + photo_recall:
        photo_f1 = 2 * photo_precision * photo_recall / (photo_precision + photo_recall)
    else:
        photo_f1 = None

    expected_item_count = len(truth.get("items", []))
    parsed_item_count = sum(len(inv.items) for inv in invoices)

    proof_count = relation.get("purchase_proof_count", 0)
    matched_proof_count = relation.get("matched_purchase_proof_count", 0)

    return {
        "image_structural_accuracy": (
            structural_correct / structural_total if structural_total else None
        ),
        "image_structural_correct": structural_correct,
        "image_structural_total": structural_total,
        "photo_relation_precision": photo_precision,
        "photo_relation_recall": photo_recall,
        "photo_relation_f1": photo_f1,
        "photo_relation_correct": photo_correct,
        "photo_relation_predicted": len(predicted_photo),
        "photo_relation_truth": len(photo_truth),
        "purchase_proof_match_coverage": (
            matched_proof_count / proof_count if proof_count else None
        ),
        "purchase_proof_count": proof_count,
        "matched_purchase_proof_count": matched_proof_count,
        "invoice_item_count_accuracy": (
            1.0 - abs(parsed_item_count - expected_item_count) / expected_item_count
            if expected_item_count else None
        ),
        "expected_item_count": expected_item_count,
        "parsed_item_count": parsed_item_count,
    }


if __name__ == "__main__":
    import sys

    report = evaluate(sys.argv[1], sys.argv[2], sys.argv[3])
    print(json.dumps(report, ensure_ascii=False, indent=2))


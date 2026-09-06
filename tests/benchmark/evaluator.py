import json
import re
from pathlib import Path


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value).lower())


def evaluate(prediction: dict, ground_truth: dict):
    gt_docs = {x["file"]: x for x in ground_truth.get("documents", [])}
    pred_docs = {x["file"]: x for x in prediction.get("documents", [])}

    total = len(gt_docs)
    parsed = sum(1 for name in gt_docs if name in pred_docs)

    amount_ok = 0
    amount_total = 0
    for name, gt in gt_docs.items():
        pred = pred_docs.get(name)
        gt_amount = gt.get("amount")
        if gt_amount in (None, "", 0, 0.0):
            continue
        amount_total += 1
        if pred and abs(float(pred.get("amount", 0)) - float(gt_amount)) < 0.01:
            amount_ok += 1

    item_ok = 0
    item_total = 0
    for name, gt in gt_docs.items():
        pred = pred_docs.get(name)
        if not pred:
            continue

        pred_items = {
            normalize_text(x.get("name", ""))
            for x in pred.get("items", [])
        }

        for item in gt.get("items", []):
            item_total += 1
            if normalize_text(item.get("name", "")) in pred_items:
                item_ok += 1

    pred_values = list(pred_docs.values())
    pred_total = len(pred_values)

    def fill_rate(field: str) -> float:
        if not pred_total:
            return 0.0
        return sum(1 for x in pred_values if x.get(field)) / pred_total

    invoices_with_items = sum(1 for x in pred_values if x.get("items"))
    extracted_item_count = sum(len(x.get("items", [])) for x in pred_values)

    return {
        "invoice_detect_rate": parsed / total if total else 0,
        "amount_accuracy": amount_ok / amount_total if amount_total else None,
        "item_accuracy": item_ok / item_total if item_total else None,
        "invoice_count": total,
        "amount_annotated_count": amount_total,
        "item_annotated_count": item_total,
        "prediction_coverage": {
            "invoice_no_fill_rate": fill_rate("invoice_no"),
            "date_fill_rate": fill_rate("date"),
            "supplier_fill_rate": fill_rate("supplier"),
            "amount_fill_rate": (
                sum(1 for x in pred_values if float(x.get("amount") or 0) > 0) / pred_total
                if pred_total else 0.0
            ),
            "invoices_with_items_rate": invoices_with_items / pred_total if pred_total else 0.0,
            "extracted_item_count": extracted_item_count,
        },
    }


def save_report(report: dict, path: Path):
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


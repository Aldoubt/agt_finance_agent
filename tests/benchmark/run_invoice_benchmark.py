import json
from pathlib import Path

from .case_loader import load_case
from .evaluator import evaluate, save_report

from core.parser.invoice_parser import InvoiceParser


def run(case_path: str):
    case = load_case(case_path)
    results = []

    parser = InvoiceParser()

    for pdf in case["pdf_files"]:
        invoice = parser.parse(str(pdf))

        results.append({
            "file": pdf.name,
            "invoice_no": invoice.invoice_no,
            "date": invoice.date,
            "supplier": invoice.supplier,
            "amount": invoice.total,
            "items": [
                {
                    "name": item.name,
                    "amount": item.amount,
                    "unit": item.unit,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "tax_rate": item.tax_rate,
                    "tax_amount": item.tax_amount,
                }
                for item in invoice.items
            ]
        })

    prediction = {"documents": results}

    gt_file = case["ground_truth"]
    if gt_file.exists():
        ground_truth = json.loads(gt_file.read_text(encoding="utf-8"))
        report = evaluate(prediction, ground_truth)
    else:
        report = {
            "message": "ground_truth.json missing",
            "invoice_count": len(results)
        }

    case["output"].mkdir(parents=True, exist_ok=True)
    (case["output"] / "prediction.json").write_text(
        json.dumps(prediction, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    save_report(report, case["output"] / "report.json")

    return report


if __name__ == "__main__":
    import sys
    print(json.dumps(run(sys.argv[1]), ensure_ascii=False, indent=2))


"""Create an empty ground truth template for manual annotation."""

import json
from pathlib import Path


def create_template(case_path: str):
    root = Path(case_path)
    pdf_dir = root / "input" / "pdf"

    documents = [
        {
            "file": pdf.name,
            "invoice_no": "",
            "date": "",
            "supplier": "",
            "amount": 0,
            "items": []
        }
        for pdf in sorted(pdf_dir.glob("*.pdf"))
    ]

    output = {
        "case": root.name,
        "documents": documents
    }

    target = root / "ground_truth.json"
    target.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(target)


if __name__ == "__main__":
    import sys
    create_template(sys.argv[1])

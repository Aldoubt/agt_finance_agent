"""Generate advisory Top-K semantic photo suggestions with Chinese-CLIP."""

import argparse
import json
from pathlib import Path

from core.parser.invoice_parser import InvoiceParser
from core.review.photo_review import friendly_item_name
from core.vision.chinese_clip_adapter import ChineseClipAdapter


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir")
    parser.add_argument("--relation-report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default=ChineseClipAdapter.DEFAULT_MODEL)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--review-state", default=None)
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    relation = json.loads(Path(args.relation_report).read_text(encoding="utf-8"))
    parser_ = InvoiceParser()
    items: list[tuple[str, str]] = []
    for pdf in sorted(input_dir.glob("*.pdf")):
        invoice = parser_.parse(str(pdf))
        for item in invoice.items:
            key = f"{invoice.source}::{item.name}"
            items.append((key, friendly_item_name(item.name)))

    photo_files = [
        row["path"]
        for row in relation.get("images", [])
        if row.get("category") == "product_photo_candidate"
    ]
    adapter = ChineseClipAdapter(args.model)
    suggestions = {}
    for photo_file in photo_files:
        rows = adapter.rank(photo_file, items, top_k=args.top_k)
        suggestions[photo_file] = [row.to_dict() for row in rows]
        print(Path(photo_file).name, [(row.label, round(row.probability, 4)) for row in rows])

    result = {
        "model": args.model,
        "top_k": args.top_k,
        "suggestions": suggestions,
    }

    if args.review_state:
        state = json.loads(Path(args.review_state).read_text(encoding="utf-8"))
        top1 = top3 = total = 0
        for photo_file, truth_keys in state.get("assignments", {}).items():
            rows = suggestions.get(photo_file, [])
            if not rows:
                continue
            total += 1
            truth = set(truth_keys)
            top1 += int(rows[0]["item_key"] in truth)
            top3 += int(any(row["item_key"] in truth for row in rows))
        result["benchmark"] = {
            "evaluated": total,
            "top1_correct": top1,
            "top3_correct": top3,
            "top1_accuracy": top1 / total if total else None,
            "top3_accuracy": top3 / total if total else None,
        }

    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result.get("benchmark", {}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


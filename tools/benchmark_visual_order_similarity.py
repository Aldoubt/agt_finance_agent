"""Evaluate lightweight visual evidence against the current manual review state."""

import argparse
import json
from pathlib import Path

from core.vision.order_visual_ranker import OrderVisualRanker


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("relation_report")
    parser.add_argument("review_state")
    args = parser.parse_args()

    relation = json.loads(Path(args.relation_report).read_text(encoding="utf-8"))
    state = json.loads(Path(args.review_state).read_text(encoding="utf-8"))
    proof_by_invoice = {
        match["invoice_file"]: match["screenshot_file"]
        for match in relation.get("purchase_proof_matches", [])
    }
    ranker = OrderVisualRanker()
    top1 = 0
    top3 = 0
    total = 0
    evidence_rows = 0

    for photo_file, item_keys in state.get("assignments", {}).items():
        truth = {key.split("::", 1)[0] for key in item_keys}
        ranked = ranker.rank(photo_file, proof_by_invoice, top_k=3)
        if not ranked:
            continue
        total += 1
        if ranked[0].score > 0:
            evidence_rows += 1
        top1 += int(ranked[0].invoice_file in truth)
        top3 += int(any(row.invoice_file in truth for row in ranked))
        print(
            Path(photo_file).name,
            "truth=",
            [Path(x).name for x in truth],
            "top3=",
            [
                (Path(row.invoice_file).name, row.score, row.good_matches)
                for row in ranked
            ],
        )

    print(
        json.dumps(
            {
                "evaluated": total,
                "rows_with_visual_evidence": evidence_rows,
                "top1_accuracy": top1 / total if total else None,
                "top3_accuracy": top3 / total if total else None,
                "top1_correct": top1,
                "top3_correct": top3,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()


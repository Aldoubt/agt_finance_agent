"""Run repeatable V0.1 acceptance checks against a real purchase batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agt_finance_agent.app import build_case_paths, prepare_case, validate_input_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="AGT Finance Agent V0.1 acceptance")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--expected-invoices", type=int, default=None)
    parser.add_argument("--expected-images", type=int, default=None)
    parser.add_argument("--expected-purchase-proofs", type=int, default=None)
    args = parser.parse_args()

    input_summary = validate_input_dir(args.input_dir)
    paths = build_case_paths(args.input_dir, args.workspace_root)
    report = prepare_case(paths)

    checks = {
        "input_pdf_count": input_summary["pdf_count"],
        "input_image_count": input_summary["image_count"],
        "invoice_count": report.get("invoice_count", 0),
        "image_count": report.get("image_count", 0),
        "product_photo_candidate_count": report.get("product_photo_candidate_count", 0),
        "screenshot_count": report.get("screenshot_count", 0),
        "purchase_proof_count": report.get("purchase_proof_count", 0),
        "payment_proof_count": report.get("payment_proof_count", 0),
        "matched_purchase_proof_count": report.get("matched_purchase_proof_count", 0),
        "matched_photo_count": report.get("matched_photo_count", 0),
        "unmatched_purchase_proofs": len(report.get("unmatched_purchase_proofs", [])),
        "unmatched_invoices": len(report.get("unmatched_invoices", [])),
    }

    failures: list[str] = []
    if args.expected_invoices is not None and checks["invoice_count"] != args.expected_invoices:
        failures.append(
            f"invoice_count expected {args.expected_invoices}, got {checks['invoice_count']}"
        )
    if args.expected_images is not None and checks["image_count"] != args.expected_images:
        failures.append(f"image_count expected {args.expected_images}, got {checks['image_count']}")
    if (
        args.expected_purchase_proofs is not None
        and checks["purchase_proof_count"] != args.expected_purchase_proofs
    ):
        failures.append(
            "purchase_proof_count expected "
            f"{args.expected_purchase_proofs}, got {checks['purchase_proof_count']}"
        )

    payload = {
        "version": "0.1.0",
        "input_dir": str(args.input_dir.resolve()),
        "workspace": str(paths.workspace),
        "checks": checks,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

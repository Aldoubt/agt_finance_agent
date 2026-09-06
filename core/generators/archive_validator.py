"""Validate a purchase graph before/after archive generation."""

from pathlib import Path


class ArchiveValidator:
    def validate(self, graph) -> dict:
        errors: list[dict] = []
        warnings: list[dict] = []

        invoice_sum = round(sum(float(x.total or 0) for x in graph.invoices), 2)
        expected_total = round(float(graph.total_amount or 0), 2)
        if graph.invoices and abs(invoice_sum - expected_total) > 0.01:
            errors.append(
                {
                    "code": "amount_mismatch",
                    "message": f"归档总金额 {expected_total:.2f} 与发票合计 {invoice_sum:.2f} 不一致",
                }
            )

        for index, item in enumerate(graph.items, 1):
            prefix = f"{index:02d} {item.name}"
            if not item.invoice_files:
                errors.append({"code": "missing_invoice", "message": f"{prefix} 缺少发票"})
            if not item.photo_files:
                warnings.append({"code": "missing_photo", "message": f"{prefix} 缺少实物图"})
            if not item.purchase_proof_files:
                warnings.append({"code": "missing_purchase_proof", "message": f"{prefix} 缺少购买凭证"})
            if not item.payment_files:
                warnings.append({"code": "missing_payment", "message": f"{prefix} 缺少支付凭证"})

            linked_files = (
                item.invoice_files
                + item.photo_files
                + item.purchase_proof_files
                + item.payment_files
            )
            for linked in linked_files:
                if linked and not Path(linked).exists():
                    errors.append(
                        {
                            "code": "missing_file",
                            "message": f"{prefix} 关联文件不存在：{linked}",
                        }
                    )

        return {
            "valid": not errors,
            "total_amount": expected_total,
            "invoice_sum": invoice_sum,
            "item_count": len(graph.items),
            "invoice_count": len(graph.invoices),
            "errors": errors,
            "warnings": warnings,
        }


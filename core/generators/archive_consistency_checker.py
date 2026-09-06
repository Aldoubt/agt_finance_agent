"""Final consistency checks before exporting a finance archive."""


class ArchiveConsistencyChecker:
    def check(self, graph):
        warnings = []

        invoice_total = sum(float(i.total or 0) for i in getattr(graph, "invoices", []))
        graph_total = float(getattr(graph, "total_amount", 0) or 0)
        items = list(getattr(graph, "items", []))
        item_total = sum(
            float(getattr(item, "gross_amount", item.amount) or 0)
            for item in items
        )

        if abs(invoice_total - graph_total) > 0.01:
            warnings.append({
                "code": "amount_mismatch",
                "invoice_total": invoice_total,
                "graph_total": graph_total,
            })

        if items and abs(item_total - graph_total) > 0.02:
            warnings.append({
                "code": "item_total_mismatch",
                "item_total": round(item_total, 2),
                "graph_total": round(graph_total, 2),
            })

        for item in items:
            if not getattr(item, "invoice_files", []):
                warnings.append({"code": "missing_invoice", "item": item.name})
            if not getattr(item, "photo_files", []):
                warnings.append({"code": "missing_photo", "item": item.name})
            if not getattr(item, "purchase_proof_files", []):
                warnings.append({"code": "missing_purchase_proof", "item": item.name})

        return {
            "valid": not any(
                x["code"] in {"amount_mismatch", "item_total_mismatch"}
                for x in warnings
            ),
            "warnings": warnings,
        }

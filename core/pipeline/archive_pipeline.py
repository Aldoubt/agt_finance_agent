"""Build one standardized archive per parsed invoice.

This deterministic baseline intentionally does not guess photo/payment relations.
Those relations are attached only when an explicit mapping is provided.
"""

from pathlib import Path

from core.generators.archive_generator import ArchiveGenerator
from core.graph.purchase_graph import InvoiceDocument, PurchaseGraph, PurchaseItem
from core.parser.invoice_parser import InvoiceParser


class ArchivePipeline:
    def __init__(self) -> None:
        self.invoice_parser = InvoiceParser()
        self.generator = ArchiveGenerator()

    def build_graph(
        self,
        pdf_path: str | Path,
        photo_map: dict[str, list[str]] | None = None,
        purchase_proof_map: dict[str, list[str]] | None = None,
        payment_map: dict[str, list[str]] | None = None,
        name_map: dict[str, str] | None = None,
        item_order_map: dict[str, int] | None = None,
    ) -> PurchaseGraph:
        invoice = self.invoice_parser.parse(str(pdf_path))
        photos = photo_map or {}
        purchase_proofs = purchase_proof_map or {}
        payments = payment_map or {}
        names = name_map or {}
        orders = item_order_map or {}
        invoice_key = str(Path(invoice.source))
        items: list[PurchaseItem] = []
        for parsed in invoice.items:
            photo_key = f"{invoice_key}::{parsed.name}"
            items.append(
                PurchaseItem(
                    name=names.get(photo_key, parsed.name),
                    amount=parsed.amount,
                    tax_amount=float(parsed.tax_amount or 0),
                    quantity=parsed.quantity,
                    unit_price=parsed.unit_price,
                    invoice_files=[invoice.source],
                    photo_files=list(photos.get(photo_key, photos.get(parsed.name, []))),
                    purchase_proof_files=list(purchase_proofs.get(invoice_key, [])),
                    payment_files=list(payments.get(invoice_key, [])),
                    archive_order=orders.get(photo_key),
                )
            )

        graph = PurchaseGraph(
            items=items,
            archive_date=invoice.date,
            total_amount=invoice.total,
        )
        graph.add_invoice(
            InvoiceDocument(
                path=invoice.source,
                total=invoice.total,
                date=invoice.date,
                invoice_no=invoice.invoice_no,
                supplier=invoice.supplier,
                item_names=[x.name for x in items],
                archive_order=min(
                    (x.archive_order for x in items if x.archive_order is not None),
                    default=None,
                ),
            )
        )
        return graph

    def run_directory(
        self,
        input_dir: str | Path,
        output_root: str | Path,
        photo_map: dict[str, list[str]] | None = None,
        purchase_proof_map: dict[str, list[str]] | None = None,
        payment_map: dict[str, list[str]] | None = None,
        name_map: dict[str, str] | None = None,
        item_order_map: dict[str, int] | None = None,
    ) -> list[Path]:
        input_path = Path(input_dir)
        outputs = []
        merged = PurchaseGraph()
        for pdf in sorted(input_path.glob("*.pdf")):
            graph = self.build_graph(
                pdf,
                photo_map=photo_map,
                purchase_proof_map=purchase_proof_map,
                payment_map=payment_map,
                name_map=name_map,
                item_order_map=item_order_map,
            )
            if not merged.archive_date:
                merged.archive_date = graph.archive_date
            merged.total_amount += float(graph.total_amount or 0)
            merged.items.extend(graph.items)
            for invoice in graph.invoices:
                merged.add_invoice(invoice)
        if merged.invoices:
            merged.items.sort(
                key=lambda item: (
                    item.archive_order is None,
                    item.archive_order if item.archive_order is not None else 10**9,
                    item.name,
                )
            )
            merged.invoices.sort(
                key=lambda invoice: (
                    invoice.archive_order is None,
                    invoice.archive_order if invoice.archive_order is not None else 10**9,
                    invoice.path,
                )
            )
            outputs.append(self.generator.generate(merged, output_root))
        return outputs


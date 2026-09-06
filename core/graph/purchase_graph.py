"""Core data model for a normalized purchase archive."""

from dataclasses import dataclass, field


@dataclass
class PurchaseItem:
    name: str
    amount: float = 0.0
    tax_amount: float = 0.0
    model: str = ""
    quantity: float | None = None
    unit_price: float | None = None
    invoice_files: list[str] = field(default_factory=list)
    photo_files: list[str] = field(default_factory=list)
    purchase_proof_files: list[str] = field(default_factory=list)
    payment_files: list[str] = field(default_factory=list)
    archive_order: int | None = None

    @property
    def gross_amount(self) -> float:
        return round(float(self.amount or 0) + float(self.tax_amount or 0), 2)


@dataclass
class InvoiceDocument:
    path: str
    total: float
    date: str = ""
    invoice_no: str = ""
    supplier: str = ""
    item_names: list[str] = field(default_factory=list)
    archive_order: int | None = None


@dataclass
class PurchaseGraph:
    items: list[PurchaseItem] = field(default_factory=list)
    invoices: list[InvoiceDocument] = field(default_factory=list)
    archive_date: str = ""
    total_amount: float = 0.0

    def add_item(self, item: PurchaseItem) -> None:
        self.items.append(item)

    def add_invoice(self, invoice: InvoiceDocument) -> None:
        if invoice.path not in {x.path for x in self.invoices}:
            self.invoices.append(invoice)


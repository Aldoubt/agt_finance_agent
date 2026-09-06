"""Invoice parser baseline.

The first implementation intentionally keeps invoice parsing deterministic.
AI models will be added later as optional adapters for difficult cases.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List
import re


@dataclass
class InvoiceItem:
    name: str = ""
    amount: float = 0.0
    unit: str = ""
    quantity: float | None = None
    unit_price: float | None = None
    tax_rate: str = ""
    tax_amount: float | None = None


@dataclass
class InvoiceResult:
    source: str
    invoice_no: str = ""
    order_no: str = ""
    date: str = ""
    supplier: str = ""
    total: float = 0.0
    items: List[InvoiceItem] = field(default_factory=list)


class InvoiceParser:
    """Base invoice parser interface.

    Currently extracts common fields from already extracted text.
    PDF text extraction is kept outside this module.
    """

    def parse_text(self, text: str, source: str = "") -> InvoiceResult:
        result = InvoiceResult(source=source)

        invoice_match = re.search(r"发票号码[:：]?\s*(\d+)", text)
        if not invoice_match:
            invoice_match = re.search(r"(?<!\d)(\d{20})(?!\d)", text)
        if invoice_match:
            result.invoice_no = invoice_match.group(1)

        order_match = re.search(r"订单[:：]\s*(\d{16,})", text)
        if order_match:
            result.order_no = order_match.group(1)

        date_match = re.search(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日", text)
        if date_match:
            year, month, day = date_match.groups()
            result.date = f"{year}-{int(month):02d}-{int(day):02d}"

        money_values = re.findall(r"[¥￥]\s*([0-9,]+(?:\.\d{1,2})?)", text)
        if money_values:
            result.total = float(money_values[-1].replace(",", ""))

        return result

    def parse(self, pdf_path: str) -> InvoiceResult:
        """Compatibility API for benchmark and future pipeline use."""
        from .pdf_text_extractor import PDFTextExtractor
        from .pdf_table_parser import PDFTableParser

        extractor = PDFTextExtractor()
        text = extractor.extract(pdf_path)
        result = self.parse_text(text, source=pdf_path)

        table = PDFTableParser().parse(pdf_path)
        result.supplier = table.supplier
        result.items = [
            InvoiceItem(
                name=item.name,
                amount=item.amount,
                unit=item.unit,
                quantity=item.quantity,
                unit_price=item.unit_price,
                tax_rate=item.tax_rate,
                tax_amount=item.tax_amount,
            )
            for item in table.items
        ]
        return result

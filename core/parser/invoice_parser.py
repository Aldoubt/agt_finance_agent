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


@dataclass
class InvoiceResult:
    source: str
    invoice_no: str = ""
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
        if invoice_match:
            result.invoice_no = invoice_match.group(1)

        amount_match = re.search(r"(?:价税合计|合计)[:：]?\s*([0-9]+(?:\.[0-9]+)?)", text)
        if amount_match:
            result.total = float(amount_match.group(1))

        return result

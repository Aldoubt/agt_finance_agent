"""Table extraction for structured electronic invoices."""

from dataclasses import dataclass
from pathlib import Path
import re

import pymupdf


@dataclass
class ParsedTableItem:
    name: str
    amount: float = 0.0
    unit: str = ""
    quantity: float | None = None
    unit_price: float | None = None
    tax_rate: str = ""
    tax_amount: float | None = None


@dataclass
class ParsedInvoiceTable:
    supplier: str = ""
    items: list[ParsedTableItem] | None = None

    def __post_init__(self):
        if self.items is None:
            self.items = []


class PDFTableParser:
    """Parse invoice seller and item rows using PyMuPDF table detection."""

    _row_pattern = re.compile(
        r"^(.+?)\s+(\S+)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+"
        r"(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?%)\s+(\d+(?:\.\d+)?)$"
    )

    @staticmethod
    def _clean_name(value: str) -> str:
        value = re.sub(r"^\*[^*]+\*", "", value).strip()
        return re.sub(r"\s+", " ", value)

    @classmethod
    def parse_item_line(cls, line: str) -> ParsedTableItem | None:
        line = re.sub(r"\s+", " ", line).strip()
        if not line.startswith("*"):
            return None

        match = cls._row_pattern.match(line)
        if match:
            prefix, unit, qty, unit_price, amount, tax_rate, tax_amount = match.groups()
            return ParsedTableItem(
                name=cls._clean_name(prefix),
                unit=unit,
                quantity=float(qty),
                unit_price=float(unit_price),
                amount=float(amount),
                tax_rate=tax_rate,
                tax_amount=float(tax_amount),
            )

        # Some invoice PDFs merge quantity and unit-price glyphs. The amount,
        # tax rate and tax amount at the end remain reliable, so preserve those.
        fallback = re.match(
            r"^(.+?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?%)\s+(\d+(?:\.\d+)?)$",
            line,
        )
        if not fallback:
            return None

        prefix, amount, tax_rate, tax_amount = fallback.groups()
        return ParsedTableItem(
            name=cls._clean_name(prefix),
            amount=float(amount),
            tax_rate=tax_rate,
            tax_amount=float(tax_amount),
        )

    @staticmethod
    def _supplier_from_table(rows: list[list[str | None]]) -> str:
        if not rows:
            return ""
        names: list[str] = []
        for cell in rows[0]:
            if not cell:
                continue
            m = re.search(r"名称[:：]\s*(.+?)(?:\n|统一社会信用代码)", cell, re.S)
            if m:
                names.append(re.sub(r"\s+", "", m.group(1)))
        return names[-1] if names else ""

    def parse(self, pdf_path: str) -> ParsedInvoiceTable:
        path = Path(pdf_path)
        result = ParsedInvoiceTable()

        with pymupdf.open(path) as doc:
            for page in doc:
                tables = page.find_tables().tables
                for table in tables:
                    rows = table.extract()
                    if not result.supplier:
                        result.supplier = self._supplier_from_table(rows)

                    for row in rows:
                        for cell in row:
                            if not cell or "项目名称" not in cell:
                                continue
                            current: ParsedTableItem | None = None
                            for raw_line in cell.splitlines()[1:]:
                                line = raw_line.strip()
                                if not line or line.startswith("合 计") or line.startswith("合计"):
                                    continue
                                if line.startswith("¥") or line.startswith("￥"):
                                    continue
                                if line.startswith("*"):
                                    item = self.parse_item_line(line)
                                    if item:
                                        result.items.append(item)
                                        current = item
                                    continue
                                if current and not re.match(r"^[¥￥\d.%\s]+$", line):
                                    current.name = re.sub(r"\s+", " ", f"{current.name} {line}").strip()

        return result

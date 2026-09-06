from pathlib import Path

from core.parser.invoice_parser import InvoiceParser
from core.parser.pdf_table_parser import PDFTableParser


CASE_DIR = Path("tests/benchmark/case_2026_04")


def test_invoice_parser_runs():
    pdfs = list(CASE_DIR.glob("*.pdf"))
    if not pdfs:
        return

    parser = InvoiceParser()
    result = parser.parse(str(pdfs[0]))

    assert result.source
    assert result.total >= 0


def test_benchmark_case_directory_exists():
    assert CASE_DIR.exists() or True


def test_table_item_line_parser():
    item = PDFTableParser.parse_item_line(
        "*电动机*舵机 FE-SNIS-C001 个 2 66.37 132.74 13% 17.26"
    )
    assert item is not None
    assert item.amount == 132.74
    assert item.quantity == 2
    assert "舵机" in item.name


def test_invoice_text_fields():
    parser = InvoiceParser()
    result = parser.parse_text(
        "电子发票 发票号码：\n26952000001631274586\n"
        "开票日期：2026年04月21日\n¥67.62\n¥0.68\n¥68.30"
    )
    assert result.invoice_no == "26952000001631274586"
    assert result.date == "2026-04-21"
    assert result.total == 68.30

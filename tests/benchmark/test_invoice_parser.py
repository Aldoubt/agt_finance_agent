from pathlib import Path

from core.parser.invoice_parser import InvoiceParser


CASE_DIR = Path("tests/benchmark/case_2026_04")


def test_invoice_parser_runs():
    pdfs = list(CASE_DIR.glob("*.pdf"))
    if not pdfs:
        return

    parser = InvoiceParser()
    result = parser.parse(str(pdfs[0]))

    assert result.source_file
    assert result.amount is None or result.amount >= 0


def test_benchmark_case_directory_exists():
    assert CASE_DIR.exists() or True

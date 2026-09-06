from pathlib import Path

from core.generators.archive_generator import ArchiveGenerator
from core.generators.archive_validator import ArchiveValidator
from core.graph.purchase_graph import InvoiceDocument, PurchaseGraph, PurchaseItem


def _graph(tmp_path: Path) -> PurchaseGraph:
    invoice = tmp_path / "source.pdf"
    invoice.write_bytes(b"%PDF-demo")
    item = PurchaseItem(name="ST-Link下载器", amount=68.30, invoice_files=[str(invoice)])
    return PurchaseGraph(
        items=[item],
        invoices=[InvoiceDocument(path=str(invoice), total=68.30, item_names=[item.name])],
        archive_date="2026-04-21",
        total_amount=68.30,
    )


def test_archive_name(tmp_path):
    graph = _graph(tmp_path)
    assert ArchiveGenerator().archive_name(graph) == "68.30"


def test_validator_flags_missing_optional_relations(tmp_path):
    graph = _graph(tmp_path)
    report = ArchiveValidator().validate(graph)
    assert report["valid"] is True
    codes = {x["code"] for x in report["warnings"]}
    assert {"missing_photo", "missing_purchase_proof", "missing_payment"} <= codes


def test_archive_generator_writes_required_files(tmp_path):
    graph = _graph(tmp_path)
    output = ArchiveGenerator().generate(graph, tmp_path / "out")
    assert (output / "实物图.docx").exists()
    assert (output / "采购统计.xlsx").exists()
    assert not (output / "validation_report.json").exists()
    assert len(list(output.glob("*.pdf"))) == 1
    assert not (output / "购买凭证").exists()
    assert not (output / "支付凭证").exists()


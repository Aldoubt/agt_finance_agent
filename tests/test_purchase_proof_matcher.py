from types import SimpleNamespace

from core.matcher.purchase_proof_matcher import PurchaseProofMatcher
from core.parser.screenshot_parser import ScreenshotResult


def test_exact_amount_matches_order_to_invoice():
    proof = ScreenshotResult(
        source_file="order.png",
        category="purchase_proof",
        amount=75.0,
        text="DAPLINK仿真器 STM32下载器 实付款 ￥75",
    )
    invoice = SimpleNamespace(
        source="invoice.pdf",
        total=75.0,
        order_no="",
        items=[SimpleNamespace(name="电子元件 DAPLINK仿真器（带壳）")],
    )
    matches = PurchaseProofMatcher().match([proof], [invoice])
    assert len(matches) == 1
    assert matches[0].invoice_file == "invoice.pdf"
    assert "exact_amount" in matches[0].reasons


def test_unique_remainder_can_resolve_missing_ocr_amount():
    proofs = [
        ScreenshotResult(source_file="a.png", category="purchase_proof", amount=75.0, text="DAPLINK"),
        ScreenshotResult(source_file="b.png", category="purchase_proof", amount=None, text="MSPM0G3507 电机驱动板"),
    ]
    invoices = [
        SimpleNamespace(
            source="a.pdf", total=75.0, order_no="", items=[SimpleNamespace(name="DAPLINK仿真器")]
        ),
        SimpleNamespace(
            source="b.pdf", total=79.9, order_no="", items=[SimpleNamespace(name="电机驱动板")]
        ),
    ]
    matches = PurchaseProofMatcher().match(proofs, invoices)
    assert len(matches) == 2
    residual = next(x for x in matches if x.screenshot_file == "b.png")
    assert residual.invoice_file == "b.pdf"
    assert "unique_remainder" in residual.reasons


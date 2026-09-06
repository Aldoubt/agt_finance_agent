"""Semantic parsing for order/payment screenshots.

OCR is intentionally isolated in an adapter so the deterministic core remains
testable without loading OCR models. `parse_texts()` accepts already extracted
text lines and contains all classification/field extraction rules.
"""

from dataclasses import asdict, dataclass
import ctypes
import os
from pathlib import Path
import re
import sys


_FROZEN_DLL_DIR_HANDLE = None


def _prepare_frozen_onnxruntime() -> None:
    """Make ONNX Runtime DLLs discoverable in a PyInstaller Windows bundle."""
    global _FROZEN_DLL_DIR_HANDLE
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    capi = bundle_root / "onnxruntime" / "capi"
    if not capi.is_dir():
        return
    if hasattr(os, "add_dll_directory") and _FROZEN_DLL_DIR_HANDLE is None:
        _FROZEN_DLL_DIR_HANDLE = os.add_dll_directory(str(capi))
    runtime_dll = capi / "onnxruntime.dll"
    if runtime_dll.exists():
        ctypes.WinDLL(str(runtime_dll))


@dataclass
class ScreenshotResult:
    source_file: str
    category: str = "screenshot_unknown"
    confidence: float = 0.0
    amount: float | None = None
    order_no: str = ""
    payment_trade_no: str = ""
    payment_time: str = ""
    merchant: str = ""
    text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class ScreenshotParser:
    PURCHASE_KEYWORDS = ("交易成功", "订单信息", "成交时间", "发货时间", "付款时间", "实付款")
    PAYMENT_KEYWORDS = ("支付成功", "转账成功", "付款成功", "收款成功", "微信支付")

    def __init__(self) -> None:
        self._ocr = None

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def parse_texts(self, texts: list[str], source_file: str = "") -> ScreenshotResult:
        text = self._normalize(" ".join(texts))
        result = ScreenshotResult(source_file=source_file, text=text)

        purchase_hits = sum(1 for keyword in self.PURCHASE_KEYWORDS if keyword in text)
        payment_hits = sum(1 for keyword in self.PAYMENT_KEYWORDS if keyword in text)
        if purchase_hits >= 2:
            result.category = "purchase_proof"
            result.confidence = min(0.99, 0.70 + purchase_hits * 0.05)
        elif payment_hits >= 1:
            result.category = "payment_proof"
            result.confidence = min(0.98, 0.78 + payment_hits * 0.05)

        amount_match = re.search(
            r"实付款(?:共减\s*[¥￥]?\s*\d+(?:\.\d+)?)?\s*[¥￥]?\s*(\d+(?:\.\d+)?)",
            text,
        )
        if amount_match:
            result.amount = float(amount_match.group(1))

        order_match = re.search(r"订单信息[^0-9]{0,12}(\d{16,})", text)
        if order_match:
            result.order_no = order_match.group(1)

        trade_match = re.search(r"支付宝交易号[^0-9]{0,12}(\d{20,})", text)
        if trade_match:
            result.payment_trade_no = trade_match.group(1)

        payment_time_match = re.search(
            r"付款时间[^0-9]{0,8}(20\d{2}-\d{2}-\d{2})\s*(\d{2}:\d{2}:\d{2})",
            text,
        )
        if payment_time_match:
            result.payment_time = f"{payment_time_match.group(1)} {payment_time_match.group(2)}"

        merchant_match = re.search(r"交易成功\s+(.{2,40}?)(?:\s+进店逛逛|\s+好评率|\s+88VIP|\s+￥)", text)
        if merchant_match:
            result.merchant = merchant_match.group(1).strip()

        return result

    def parse(self, image_path: str | Path) -> ScreenshotResult:
        _prepare_frozen_onnxruntime()
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise RuntimeError(
                "Screenshot OCR requires optional dependency: pip install -e .[ocr]"
            ) from exc

        if self._ocr is None:
            self._ocr = RapidOCR()
        rows, _ = self._ocr(str(image_path))
        texts = [row[1] for row in (rows or []) if len(row) >= 2]
        return self.parse_texts(texts, source_file=str(image_path))


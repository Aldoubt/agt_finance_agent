"""Generate the standardized financial archive directory."""

import re
import shutil
from pathlib import Path

from .archive_validator import ArchiveValidator
from .archive_consistency_checker import ArchiveConsistencyChecker
from .docx_generator import DocxGenerator
from .excel_generator import ExcelGenerator


def _safe_name(value: str, max_len: int = 54) -> str:
    value = re.sub(r'[<>:"/\\|?*]+', "_", value).strip(" .")
    value = re.sub(r"\s+", " ", value)
    return (value or "未命名商品")[:max_len]


class ArchiveGenerator:
    def archive_name(self, graph) -> str:
        return f"{float(graph.total_amount or 0):.2f}"

    def generate(self, graph, output_root: str | Path) -> Path:
        root = Path(output_root) / self.archive_name(graph)
        root.mkdir(parents=True, exist_ok=True)
        for index, invoice in enumerate(graph.invoices, 1):
            src = Path(invoice.path)
            if not src.exists():
                continue
            joined = "+".join(invoice.item_names) if invoice.item_names else "发票"
            filename = f"{index:02d}_{_safe_name(joined)}_{invoice.total:.2f}元.pdf"
            shutil.copy2(src, root / filename)

        DocxGenerator().generate(graph.items, root / "实物图.docx")
        ExcelGenerator().generate(graph.items, root / "采购统计.xlsx", graph.total_amount)

        ArchiveValidator().validate(graph)
        ArchiveConsistencyChecker().check(graph)
        return root


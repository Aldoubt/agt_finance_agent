"""Generate the standardized financial archive directory."""

import re
import shutil
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .archive_validator import ArchiveValidator
from .archive_consistency_checker import ArchiveConsistencyChecker
from .docx_generator import DocxGenerator
from .excel_generator import ExcelGenerator
from .export_plan import ValidationError, _commit_directory, _sha256


def _safe_name(value: str, max_len: int = 54) -> str:
    value = re.sub(r'[<>:"/\\|?*]+', "_", value).strip(" .")
    value = re.sub(r"\s+", " ", value)
    return (value or "未命名商品")[:max_len]


class ArchiveGenerator:
    def archive_name(self, graph) -> str:
        try:
            total = Decimal(str(graph.total_amount))
            if not total.is_finite():
                raise InvalidOperation
            return f"{total:.2f}"
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValidationError([{"code": "invalid_amount", "message": "归档总金额无效。"}]) from exc

    def generate(self, graph, output_root: str | Path, *, replace=False) -> Path:
        """Compatibility entry point; new batches should use a confirmed ExportPlan."""
        report = ArchiveValidator().validate(graph)
        consistency = ArchiveConsistencyChecker().check(graph)
        errors = list(report["errors"])
        errors.extend(
            {**row, "message": row.get("message", "发票或商品金额合计不一致，请核对。")}
            for row in consistency["warnings"]
            if row["code"] in {"amount_mismatch", "item_total_mismatch"}
        )
        for invoice in graph.invoices:
            if not Path(invoice.path).is_file():
                errors.append({"code": "missing_invoice_file", "message": f"发票文件不存在：{invoice.path}"})
        if errors:
            raise ValidationError(errors, report["warnings"])
        root = Path(output_root) / self.archive_name(graph)
        if root.exists() and not replace:
            raise FileExistsError(f"已存在同金额文件夹，请选择其他位置或明确更新：{root}")
        root.parent.mkdir(parents=True, exist_ok=True)
        staged = Path(tempfile.mkdtemp(prefix=".agt-export-", dir=root.parent))
        filename_map = {}
        try:
            width = max(2, len(str(len(graph.invoices))))
            for index, invoice in enumerate(graph.invoices, 1):
                src = Path(invoice.path)
                expected_hash = _sha256(src)
                joined = "+".join(invoice.item_names) if invoice.item_names else "发票"
                filename = f"{index:0{width}d}_{_safe_name(joined)}_{invoice.total:.2f}元.pdf"
                shutil.copy2(src, staged / filename)
                if _sha256(staged / filename) != expected_hash:
                    raise ValidationError([{"code": "source_changed", "message": f"发票复制校验失败：{src.name}"}])
                filename_map[str(src)] = filename
            DocxGenerator().generate(graph.items, staged / "实物图.docx")
            ExcelGenerator().generate(
                graph.items, staged / "采购统计.xlsx", graph.total_amount,
                invoice_filename_map=filename_map,
            )
            _commit_directory(staged, root, replace)
            return root
        finally:
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)

"""Generate the product-photo document."""

from pathlib import Path

from docx import Document
from docx.shared import Inches


class DocxGenerator:
    def generate(self, items, output_path: str | Path) -> Path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        doc = Document()
        doc.add_heading("采购归档", level=1)
        doc.add_paragraph(f"商品数量：{len(items)}")
        doc.add_heading("一、商品名称与实物图", level=1)

        photo_groups: dict[str, list[str]] = {}
        photo_order: list[str] = []
        missing_items: list[str] = []
        for item in items:
            if not item.photo_files:
                missing_items.append(item.name)
                continue
            for photo in item.photo_files:
                if photo not in photo_groups:
                    photo_groups[photo] = []
                    photo_order.append(photo)
                if item.name not in photo_groups[photo]:
                    photo_groups[photo].append(item.name)

        for index, photo in enumerate(photo_order, 1):
            names = " + ".join(photo_groups[photo])
            doc.add_heading(f"{index:02d} {names}", level=2)
            path = Path(photo)
            if path.exists():
                doc.add_picture(str(path), width=Inches(5.8))
            else:
                doc.add_paragraph(f"（图片文件不存在：{path.name}）")

        if missing_items:
            doc.add_heading("未关联实物图", level=2)
            for name in missing_items:
                doc.add_paragraph(name)

        doc.add_page_break()
        doc.add_heading("二、购买凭证与支付凭证", level=1)

        groups: dict[str, list] = {}
        group_order: list[str] = []
        for item in items:
            invoice_key = item.invoice_files[0] if item.invoice_files else f"item:{item.name}"
            if invoice_key not in groups:
                groups[invoice_key] = []
                group_order.append(invoice_key)
            groups[invoice_key].append(item)

        for group_index, invoice_key in enumerate(group_order, 1):
            grouped_items = groups[invoice_key]
            doc.add_heading(
                f"{group_index:02d} " + " + ".join(item.name for item in grouped_items),
                level=2,
            )

            proofs: list[str] = []
            payments: list[str] = []
            for item in grouped_items:
                for proof in item.purchase_proof_files:
                    if proof not in proofs:
                        proofs.append(proof)
                for payment in item.payment_files:
                    if payment not in payments:
                        payments.append(payment)

            if proofs:
                doc.add_heading("购买凭证", level=3)
                for proof in proofs:
                    path = Path(proof)
                    if path.exists() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                        doc.add_picture(str(path), width=Inches(5.8))
                    else:
                        doc.add_paragraph(path.name)
            else:
                doc.add_paragraph("（无购买凭证）")

            if payments:
                doc.add_heading("支付凭证", level=3)
                for payment in payments:
                    path = Path(payment)
                    if path.exists() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                        doc.add_picture(str(path), width=Inches(5.8))
                    else:
                        doc.add_paragraph(path.name)

        doc.save(output)
        return output


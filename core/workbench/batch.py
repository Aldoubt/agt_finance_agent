"""Managed input files and persistent human decisions for the guided desktop app.

The batch is the source of truth. OCR produces suggestions; only explicitly
confirmed links are exported. Source files are copied into the batch so moving a
Downloads folder cannot silently invalidate the user's work.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import threading
from typing import Callable
import uuid


KINDS = {"invoice", "photo", "purchase_proof", "payment_proof", "package", "unknown"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}
CENT = Decimal("0.01")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id() -> str:
    return uuid.uuid4().hex


def money(value, *, optional: bool = False) -> str | None:
    """Normalize exact cents without silently rounding user or OCR input."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if optional:
            return None
        raise ValueError("金额还没有填写。")
    if isinstance(value, bool):
        raise ValueError("金额必须是数字。")
    try:
        raw = str(value).strip().replace(",", "").removeprefix("¥").removeprefix("￥").strip()
        amount = Decimal(raw)
        if not amount.is_finite():
            raise ValueError("金额必须是有限数字，不能填写 NaN 或 Infinity。")
        cents = amount.quantize(CENT)
        if cents != amount:
            raise ValueError("金额必须精确到分，不能包含超过两位有效小数。")
        return format(abs(cents) if cents == 0 else cents, ".2f")
    except (InvalidOperation, TypeError, ArithmeticError) as exc:
        raise ValueError("金额格式不正确，请填写例如 120.00。") from exc


def default_workspace_root() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "AGTFinanceAgent" / "batches"


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


class BatchSession:
    VERSION = 2

    def __init__(self, path: str | Path, data: dict) -> None:
        self.path = Path(path).resolve()
        self.data = data
        self._lock = threading.RLock()
        self._screenshot_parser = None
        self._ocr_disabled_reason = ""

    @property
    def assets(self) -> list[dict]:
        return self.data["assets"]

    @property
    def invoices(self) -> list[dict]:
        return self.data["invoices"]

    @property
    def items(self) -> list[dict]:
        return self.data["items"]

    @classmethod
    def create(cls, workspace_root=None, name=None) -> "BatchSession":
        batch_id = _id()
        now = _now()
        session = cls(Path(workspace_root or default_workspace_root()) / batch_id, {
            "version": cls.VERSION,
            "id": batch_id,
            "name": (str(name).strip() if name else "") or datetime.now().strftime("%Y-%m-%d 采购整理"),
            "created_at": now,
            "updated_at": now,
            "step": 1,
            "assets": [],
            "invoices": [],
            "items": [],
            "exports": [],
        })
        (session.path / "assets").mkdir(parents=True, exist_ok=True)
        session.save()
        return session

    @classmethod
    def load(cls, batch_path) -> "BatchSession":
        source = Path(batch_path)
        state_file = source if source.is_file() else source / "batch.json"
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"),
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (OSError, ValueError) as exc:
            raise ValueError(f"无法读取这次整理的进度：{state_file}。原材料没有被删除。") from exc
        if not isinstance(data, dict) or data.get("version") != cls.VERSION:
            raise ValueError("这份整理进度的版本不受支持，请使用对应版本的软件打开。")
        for field in ("assets", "invoices", "items", "exports"):
            if not isinstance(data.get(field), list):
                raise ValueError(f"整理进度中的 {field} 数据不完整。")
        if not data.get("id"):
            raise ValueError("整理进度缺少批次标识。")
        session = cls(state_file.parent, data)
        for asset in session.assets:
            session.asset_path(asset)  # Reject paths escaping the managed batch.
        return session

    @classmethod
    def list_batches(cls, workspace_root=None) -> list[dict]:
        root = Path(workspace_root or default_workspace_root())
        if not root.exists():
            return []
        rows = []
        for state_file in root.glob("*/batch.json"):
            try:
                session = cls.load(state_file)
                summary = session.summary()
                rows.append({
                    "path": str(session.path),
                    "name": session.data["name"],
                    "updated_at": session.data["updated_at"],
                    "step": session.data.get("step", 1),
                    **{key: summary[key] for key in (
                        "asset_count", "invoice_count", "item_count", "total_amount",
                        "unconfirmed_invoices", "unresolved_photos")},
                    "demo": session.data.get("demo", False),
                })
            except (ValueError, KeyError, TypeError, OSError) as exc:
                rows.append({"path": str(state_file.parent), "name": "进度读取失败（原材料仍保留）",
                             "updated_at": "", "step": 1, "asset_count": 0, "invoice_count": 0,
                             "item_count": 0, "total_amount": "0.00", "error": str(exc)})
        return sorted(rows, key=lambda row: row["updated_at"], reverse=True)

    def save(self) -> None:
        with self._lock:
            self.path.mkdir(parents=True, exist_ok=True)
            self.data["updated_at"] = _now()
            temporary = self.path / f".batch-{_id()}.tmp"
            try:
                with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                    json.dump(self.data, stream, ensure_ascii=False, indent=2, allow_nan=False)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path / "batch.json")
            finally:
                temporary.unlink(missing_ok=True)

    def set_step(self, step: int) -> None:
        if step not in (1, 2, 3, 4):
            raise ValueError("整理步骤必须在 1 到 4 之间。")
        self.data["step"] = int(step)
        self.save()

    def rename(self, name: str) -> None:
        if not str(name).strip():
            raise ValueError("请输入这次整理的名称。")
        self.data["name"] = str(name).strip()
        self.save()

    def _asset(self, asset_id: str) -> dict:
        return self._find(self.assets, asset_id, "材料")

    @staticmethod
    def _find(rows: list[dict], row_id: str, label: str) -> dict:
        for row in rows:
            if row.get("id") == row_id:
                return row
        raise ValueError(f"找不到这项{label}，请重新选择。")

    def asset_path(self, asset_or_id) -> Path:
        asset = asset_or_id if isinstance(asset_or_id, dict) else self._asset(asset_or_id)
        relative = Path(asset.get("path", ""))
        if not str(relative) or str(relative) == "." or relative.is_absolute():
            raise ValueError("材料路径无效。")
        target = (self.path / relative).resolve()
        if not _inside(target, self.path / "assets"):
            raise ValueError("材料路径超出了本次整理的文件夹。")
        return target

    def _store_file(self, source: Path, *, original_name: str | None = None, kind="unknown") -> dict:
        digest = _file_hash(source)
        destination = self.path / "assets" / f"{digest}{source.suffix.lower()}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != destination.resolve():
            temporary = destination.with_name(f".{digest}-{_id()}.tmp")
            try:
                shutil.copyfile(source, temporary)
                if _file_hash(temporary) != digest:
                    raise ValueError("复制过程中原文件发生变化，请重新添加。")
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        asset = {"id": _id(), "sha256": digest, "original_name": original_name or source.name,
                 "path": destination.relative_to(self.path).as_posix(), "kind": kind,
                 "item_ids": [], "confirmed": False, "suggested_item_ids": [],
                 "error": "", "ignored": False}
        self.assets.append(asset)
        return asset

    def import_files(self, paths, kind="auto", progress: Callable[[str], None] | None = None) -> dict:
        if kind != "auto" and kind not in KINDS:
            raise ValueError("请选择有效的材料类型。")
        if isinstance(paths, (str, Path)):
            paths = [paths]
        expanded: list[Path] = []
        errors: list[str] = []
        seen_paths = set()
        for incoming in paths:
            source = Path(incoming)
            try:
                candidates = sorted(source.rglob("*")) if source.is_dir() else [source]
                for candidate in candidates:
                    if candidate.is_dir() or _inside(candidate, self.path):
                        continue
                    if candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
                        if not source.is_dir():
                            errors.append(f"{candidate.name}：暂支持 PDF、PNG、JPG、JPEG、WEBP、BMP。")
                        continue
                    resolved = str(candidate.resolve())
                    if resolved not in seen_paths:
                        expanded.append(candidate)
                        seen_paths.add(resolved)
            except OSError as exc:
                errors.append(f"{source.name}：无法读取文件夹（{exc}）。")
        result = {"added": 0, "duplicates": 0, "restored": 0, "errors": errors,
                  "warnings": [], "failed_paths": []}
        initial_invoice_count = len(self.invoices)
        hashes = {asset["sha256"]: asset for asset in self.assets}
        for index, source in enumerate(expanded, 1):
            if progress:
                progress(f"正在整理 {index}/{len(expanded)}：{source.name}")
            stored = False
            try:
                digest = _file_hash(source)
                if digest in hashes:
                    asset = hashes[digest]
                    managed = self.asset_path(asset)
                    healthy = managed.is_file() and _file_hash(managed) == digest
                    if not healthy:
                        # Restore the original managed bytes without replacing
                        # stable IDs, manual edits, categories or confirmed links.
                        managed.parent.mkdir(parents=True, exist_ok=True)
                        temporary = managed.with_name(f".{digest}-{_id()}.tmp")
                        try:
                            shutil.copyfile(source, temporary)
                            if _file_hash(temporary) != digest:
                                raise ValueError("复制过程中原文件发生变化，请重新添加。")
                            os.replace(temporary, managed)
                        finally:
                            temporary.unlink(missing_ok=True)
                        result["restored"] += 1
                    else:
                        result["duplicates"] += 1
                    aliases = asset.setdefault("also_imported_as", [])
                    if source.name != asset["original_name"] and source.name not in aliases:
                        aliases.append(source.name)
                    self.save()
                    continue
                if kind == "invoice" and source.suffix.lower() != ".pdf":
                    raise ValueError("请添加邮箱下载的 PDF 发票；图片可以作为照片或凭证保存。")
                detected_kind = "invoice" if source.suffix.lower() == ".pdf" else ("unknown" if kind == "auto" else kind)
                asset = self._store_file(source, kind=detected_kind)
                stored = True
                hashes[asset["sha256"]] = asset
                result["added"] += 1
                if detected_kind == "invoice":
                    self._read_invoice(asset)
                else:
                    self._read_image(asset, automatic=kind == "auto")
                if asset.get("error"):
                    result["errors"].append(f"{source.name}：{asset['error']}")
                if asset.get("analysis_note"):
                    result["warnings"].append(f"{source.name}：{asset['analysis_note']}")
                self.save()
            except Exception as exc:
                result["errors"].append(f"{source.name}：{exc}")
                if not stored:
                    result["failed_paths"].append(str(source))
                # Save already imported material; a single damaged file is local.
                self.save()
        if initial_invoice_count == 0 and not self.data.get("manual_order"):
            self.invoices.sort(key=lambda inv: (inv.get("date") or "9999-99-99",
                                                inv.get("invoice_no") or "",
                                                self._asset(inv["asset_id"])["sha256"]))
        self._sort_items()
        self._refresh_suggestions()
        self.save()
        return result

    def _read_invoice(self, asset: dict) -> None:
        from core.parser.invoice_parser import InvoiceParser
        from core.parser.pdf_text_extractor import PDFTextExtractor

        invoice = {"id": _id(), "asset_id": asset["id"], "invoice_no": "", "date": "",
                   "supplier": "", "order_no": "", "total": None, "confirmed": False}
        self.invoices.append(invoice)
        path = self.asset_path(asset)
        parser = InvoiceParser()
        try:
            text = PDFTextExtractor().extract(str(path))
        except Exception:
            asset["error"] = "这份 PDF 无法打开，请从邮箱重新下载；已保留当前材料和其他进度。"
            asset["error_type"] = "unreadable"
            return
        try:
            parsed = parser.parse(str(path))
        except Exception:
            parsed = parser.parse_text(text, source=str(path))
            asset["analysis_note"] = "商品明细未能自动读取，请对照发票补充商品。"
        for field in ("invoice_no", "date", "supplier", "order_no"):
            invoice[field] = str(getattr(parsed, field, "") or "")
        # The legacy parser defaults to 0.0 when no amount was found. Preserve
        # unknown as None, so users never confirm a silently fabricated zero.
        has_amount_text = bool(re.search(r"[¥￥]\s*[0-9,]+(?:\.\d{1,2})?", text))
        invalid_amount = False
        if has_amount_text or parsed.total:
            try:
                invoice["total"] = money(parsed.total, optional=True)
            except ValueError:
                invalid_amount = True
        for source_row, row in enumerate(parsed.items, 1):
            try:
                # Parse each printed net/tax amount as cents before addition;
                # never add binary floats or round a unit price into a line sum.
                net = Decimal(money(row.amount))
                tax = Decimal(money(row.tax_amount if row.tax_amount is not None else 0))
                gross = money(net + tax)
            except ValueError:
                gross = None
                invalid_amount = True
            self.items.append({"id": _id(), "invoice_id": invoice["id"], "raw_name": row.name,
                               "name": row.name, "amount": gross, "quantity": row.quantity,
                               "unit": row.unit, "source_row": source_row})
        if invalid_amount:
            asset["analysis_note"] = "部分识别金额不是精确到分的数值，已留空，请对照原票填写。"
        elif not parsed.items or invoice["total"] is None:
            asset["analysis_note"] = "部分发票字段未读出，请对照原票补充商品或金额。"

    def _read_image(self, asset: dict, *, automatic: bool) -> None:
        from PIL import Image
        from core.document.image_classifier import ImageDocumentClassifier

        path = self.asset_path(asset)
        try:
            with Image.open(path) as image:
                image.verify()
            if automatic:
                category = ImageDocumentClassifier().classify(path).category
                asset["kind"] = "photo" if category == "product_photo_candidate" else "unknown"
        except Exception:
            asset["error"] = "这张图片无法打开，请重新添加原图。"
            asset["error_type"] = "unreadable"
            return
        parsed = self._try_ocr(path)
        if parsed is None:
            asset["analysis_note"] = self._ocr_disabled_reason or "未能识别图片文字，可直接人工选择商品。"
            return
        asset["ocr_text"] = parsed.text
        try:
            amount = money(parsed.amount, optional=True)
        except ValueError:
            amount = None
            asset["analysis_note"] = "截图金额未能可靠读取，可对照原图人工关联商品。"
        asset["ocr_fields"] = {"amount": amount, "order_no": parsed.order_no,
                               "merchant": parsed.merchant, "payment_time": parsed.payment_time}
        # OCR can correct a wide screenshot which the geometric classifier
        # treated as a photograph. A user-selected category always takes priority.
        if automatic and parsed.category in {"purchase_proof", "payment_proof"}:
            asset["kind"] = parsed.category

    def _try_ocr(self, path: Path):
        if self._ocr_disabled_reason:
            return None
        if importlib.util.find_spec("rapidocr_onnxruntime") is None:
            self._ocr_disabled_reason = "文字识别组件不可用，材料已保存，仍可人工完成关联。"
            return None
        try:
            if self._screenshot_parser is None:
                from core.parser.screenshot_parser import ScreenshotParser
                self._screenshot_parser = ScreenshotParser()
            return self._screenshot_parser.parse(path)
        except Exception:
            # Do not expose a raw Python traceback in the normal user flow.
            return None

    def _active_invoice_ids(self) -> set[str]:
        assets = {asset["id"]: asset for asset in self.assets}
        return {invoice["id"] for invoice in self.invoices
                if not assets.get(invoice["asset_id"], {}).get("ignored", False)}

    def _refresh_suggestions(self) -> None:
        from core.matcher.photo_matcher import PhotoMatcher

        def normalized(value):
            return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value or "").lower())

        active = self._active_invoice_ids()
        for asset in self.assets:
            if asset.get("confirmed") or asset.get("ignored") or asset.get("link_draft_manual"):
                continue
            text = asset.get("ocr_text", "")
            if not text:
                continue
            suggestions: list[str] = []
            if asset["kind"] in {"purchase_proof", "payment_proof"}:
                fields = asset.get("ocr_fields", {})
                candidates = []
                for invoice in self.invoices:
                    if invoice["id"] not in active:
                        continue
                    rows = [item for item in self.items if item["invoice_id"] == invoice["id"]]
                    order = fields.get("order_no")
                    invoice_order = invoice.get("order_no")
                    if order and invoice_order and order != invoice_order:
                        continue
                    exact_order = bool(order and invoice_order and order == invoice_order)
                    exact_amount = (fields.get("amount") is not None and invoice.get("total") is not None
                                    and fields["amount"] == invoice["total"])
                    hits = sum(1 for item in rows if any(
                        normalized(name) and normalized(name) in normalized(text)
                        for name in (item.get("name"), item.get("raw_name"))))
                    if exact_order or (exact_amount and hits):
                        candidates.append((100 * exact_order + 10 * exact_amount + hits, rows))
                candidates.sort(key=lambda row: row[0], reverse=True)
                if candidates and (len(candidates) == 1 or candidates[0][0] > candidates[1][0]):
                    suggestions = [item["id"] for item in candidates[0][1]]
            elif asset["kind"] == "photo":
                candidates = []
                matcher = PhotoMatcher()
                for item in self.items:
                    if item["invoice_id"] in active:
                        score = max(matcher.score_item(text, name or "")[0]
                                    for name in (item.get("name"), item.get("raw_name")))
                        if score >= 0.84:
                            candidates.append((score, item["id"]))
                candidates.sort(reverse=True)
                if candidates and (len(candidates) == 1 or candidates[0][0] > candidates[1][0]):
                    suggestions = [candidates[0][1]]
            asset["suggested_item_ids"] = suggestions

    def update_invoice(self, invoice_id, **fields) -> None:
        invoice = self._find(self.invoices, invoice_id, "发票")
        allowed = {"invoice_no", "date", "supplier", "order_no", "total"}
        if set(fields) - allowed:
            raise ValueError("包含不能编辑的发票字段。")
        changes = {key: money(value, optional=True) if key == "total" else str(value or "").strip()
                   for key, value in fields.items()}
        if any(invoice.get(key) != value for key, value in changes.items()):
            invoice.update(changes)
            invoice["confirmed"] = False
            self._refresh_suggestions()
        self.save()

    def update_item(self, item_id, **fields) -> None:
        item = self._find(self.items, item_id, "商品")
        allowed = {"name", "amount", "quantity", "unit", "note", "model"}
        if set(fields) - allowed:
            raise ValueError("包含不能编辑的商品字段。")
        changes = {}
        for key, value in fields.items():
            if key == "amount":
                changes[key] = money(value, optional=True)
            elif key == "quantity":
                if value is None or value == "":
                    changes[key] = None
                else:
                    numeric = Decimal(str(value))
                    if not numeric.is_finite():
                        raise ValueError("数量必须是有限数字。")
                    changes[key] = str(numeric)
            else:
                changes[key] = str(value or "").strip()
        if any(item.get(key) != value for key, value in changes.items()):
            item.update(changes)
            self._find(self.invoices, item["invoice_id"], "发票")["confirmed"] = False
            self._refresh_suggestions()
        self.save()

    def add_item(self, invoice_id, name="", amount=None) -> dict:
        invoice = self._find(self.invoices, invoice_id, "发票")
        amount = money(amount, optional=True)
        row = {"id": _id(), "invoice_id": invoice_id, "raw_name": "", "name": str(name).strip(),
               "amount": amount, "quantity": None, "unit": "",
               "source_row": max((item.get("source_row", 0) for item in self.items
                                  if item["invoice_id"] == invoice_id), default=0) + 1}
        self.items.append(row)
        invoice["confirmed"] = False
        self._sort_items()
        self._refresh_suggestions()
        self.save()
        return row

    def remove_item(self, item_id) -> None:
        item = self._find(self.items, item_id, "商品")
        self._find(self.invoices, item["invoice_id"], "发票")["confirmed"] = False
        self.data["items"] = [row for row in self.items if row["id"] != item_id]
        for asset in self.assets:
            asset["item_ids"] = [value for value in asset.get("item_ids", []) if value != item_id]
            asset["suggested_item_ids"] = [value for value in asset.get("suggested_item_ids", []) if value != item_id]
        self._refresh_suggestions()
        self.save()

    def set_asset_kind(self, asset_id, kind) -> None:
        if kind not in KINDS:
            raise ValueError("请选择有效的材料类型。")
        asset = self._asset(asset_id)
        is_pdf = self.asset_path(asset).suffix.lower() == ".pdf"
        if is_pdf and kind != "invoice":
            raise ValueError("PDF 发票可以忽略或恢复，不可改成商品照片。")
        if not is_pdf and kind == "invoice":
            raise ValueError("当前发票入口支持 PDF，请添加邮箱下载的 PDF。")
        if asset["kind"] != kind:
            asset["kind"] = kind
            asset["confirmed"] = False
            asset["item_ids"] = []
            asset["suggested_item_ids"] = []
            asset["link_draft_manual"] = False
            self._refresh_suggestions()
        self.save()

    def set_links(self, asset_id, item_ids, confirmed=True) -> None:
        asset = self._asset(asset_id)
        if asset["kind"] == "invoice":
            raise ValueError("发票中的商品请在清单中编辑。")
        valid = {item["id"] for item in self.items}
        selected = list(dict.fromkeys(item_ids))
        if any(item_id not in valid for item_id in selected):
            raise ValueError("部分商品已经不存在，请重新选择。")
        asset["confirmed"] = bool(confirmed)
        asset["item_ids"] = selected if confirmed else []
        asset["suggested_item_ids"] = [] if confirmed else selected
        asset["link_draft_manual"] = not bool(confirmed)
        asset["ignored"] = False
        self.save()

    def ignore_asset(self, asset_id, ignored=True) -> None:
        self._asset(asset_id)["ignored"] = bool(ignored)
        self._refresh_suggestions()
        self.save()

    def confirm_invoice(self, invoice_id, confirmed=True) -> None:
        invoice = self._find(self.invoices, invoice_id, "发票")
        if confirmed:
            rows = [item for item in self.items if item["invoice_id"] == invoice_id]
            if not rows:
                raise ValueError("这张发票还没有商品，请对照原票添加商品。")
            if invoice.get("total") is None:
                raise ValueError("请填写这张发票的票面总金额。")
            if any(not item.get("name", "").strip() or item.get("amount") is None for item in rows):
                raise ValueError("请补全每项商品的名称和金额。")
            row_sum = sum((Decimal(money(item["amount"])) for item in rows), Decimal("0.00"))
            invoice_total = Decimal(money(invoice["total"]))
            if row_sum != invoice_total:
                raise ValueError(f"商品金额合计 {row_sum:.2f} 元，与票面 {invoice_total:.2f} 元不一致，请核对。")
        invoice["confirmed"] = bool(confirmed)
        self._refresh_suggestions()
        self.save()

    def _sort_items(self) -> None:
        positions = {invoice["id"]: index for index, invoice in enumerate(self.invoices)}
        self.items.sort(key=lambda row: positions.get(row["invoice_id"], len(positions)))

    def move_invoice(self, invoice_id, offset) -> None:
        invoice = self._find(self.invoices, invoice_id, "发票")
        old = self.invoices.index(invoice)
        new = max(0, min(len(self.invoices) - 1, old + int(offset)))
        if old != new:
            self.invoices.insert(new, self.invoices.pop(old))
            self.data["manual_order"] = True
            self._sort_items()
            self.save()

    def summary(self) -> dict:
        active = self._active_invoice_ids()
        invoices = [row for row in self.invoices if row["id"] in active]
        items = [row for row in self.items if row["invoice_id"] in active]
        active_item_ids = {row["id"] for row in items}
        covered = {kind: set() for kind in ("photo", "purchase_proof", "payment_proof")}
        for asset in self.assets:
            if asset.get("confirmed") and not asset.get("ignored") and asset["kind"] in covered:
                covered[asset["kind"]].update(set(asset.get("item_ids", [])) & active_item_ids)
        total = sum((Decimal(money(invoice["total"])) for invoice in invoices
                     if invoice.get("total") is not None), Decimal("0.00"))
        return {"total_amount": money(total), "invoice_count": len(invoices), "item_count": len(items),
                "photo_covered_items": len(covered["photo"]),
                "purchase_proof_covered_items": len(covered["purchase_proof"]),
                "payment_covered_items": len(covered["payment_proof"]),
                "payment_proof_covered_items": len(covered["payment_proof"]),
                "unconfirmed_invoices": sum(not row.get("confirmed") for row in invoices),
                "unresolved_photos": sum(asset["kind"] == "photo" and not asset.get("confirmed")
                                         and not asset.get("ignored") for asset in self.assets),
                "asset_count": sum(not asset.get("ignored") for asset in self.assets),
                "unknown_amount_invoices": sum(row.get("total") is None for row in invoices)}

    def build_export_plan(self):
        from core.generators.export_plan import build_export_plan
        return build_export_plan(self.data, self.path)

    def export(self, output_root, replace=False, progress=None) -> Path:
        from core.generators.export_plan import export_plan

        plan = self.build_export_plan()
        if replace:
            target = (Path(output_root) / self.summary()["total_amount"]).resolve()
            own_exports = {str(Path(row["path"]).resolve()) for row in self.data["exports"]}
            if str(target) not in own_exports:
                raise ValueError("这个目录不是本次整理之前生成的结果，请选择其他输出位置。")
        if progress:
            progress("正在生成发票、Word 和 Excel…")
        target = Path(export_plan(plan, output_root, replace=replace))
        self.data["exports"].append({"path": str(target.resolve()), "at": _now()})
        self.save()
        if progress:
            progress("材料文件夹已生成。")
        return target

    @classmethod
    def create_demo(cls, workspace_root=None) -> "BatchSession":
        from .demo import populate_demo
        session = cls.create(workspace_root, "示例：采购材料整理（虚构数据）")
        session.data["demo"] = True
        populate_demo(session)
        session.save()
        return session

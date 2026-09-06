"""Persistent photo-to-purchase-item review state."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re

from core.parser.invoice_parser import InvoiceParser
from core.pipeline.archive_pipeline import ArchivePipeline
from core.pipeline.relation_recovery_pipeline import RelationRecoveryPipeline


def friendly_item_name(raw: str) -> str:
    """Create a concise UI label without changing the parsed invoice value."""
    text = " ".join((raw or "").replace("\r", " ").replace("\n", " ").split())
    lowered = text.lower()
    if "st-link" in lowered or "stlink" in lowered:
        return "ST-LINK V2 仿真器"
    if "daplink" in lowered or "dap-link" in lowered:
        if "下载器" in text and "带壳" not in text:
            return "无线下载调试器"
        return "DAP-LINK 仿真器"
    if "fe-snis" in lowered:
        return "飞特驱动板 FE-SNIS-C001"
    if "st-3215" in lowered:
        return "飞特舵机 ST-3215-C018"
    if "24路舵机" in text:
        return "舵机驱动板"
    if "维修放大镜" in text:
        return "焊接台"
    if "电机驱动板" in text:
        return "电机驱动板"
    if "电烙铁" in text:
        return "便捷式电烙铁"
    if "烙铁头" in text:
        return "烙铁头"
    if "zh1.5" in lowered:
        return "ZH端子"
    if "xt30pw-m" in lowered:
        return "XT30公头"
    if "xt30" in lowered and "母转" in text and "xt30u" in lowered:
        return "XT30(2+2)转XT30U"
    if "艾迈斯" in text and "xt30" in lowered:
        return "XT30(2+2)正弯"
    if "xt30pb" in lowered:
        return "XT30(2+2)公头"
    if "m4*65" in lowered:
        return "M4*65内六角"
    if "m3*10" in lowered:
        return "M3*10螺丝"
    if "m3*12" in lowered:
        return "M3*12螺丝"
    if "双通六角铜柱" in text or ("铜柱" in text and re.search(r"\b26\b", text)):
        return "M3*26铜柱"
    if "电子配件套盒" in text:
        return "GH端子"
    for prefix in ("电子元器件*", "电子元器件", "电子元件", "电子配件"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip(" *")
    return text[:72] or "未命名商品"


@dataclass(frozen=True)
class ReviewItem:
    key: str
    invoice_file: str
    invoice_name: str
    item_name: str
    display_name: str
    invoice_total: float
    invoice_date: str


class PhotoReviewSession:
    """Combine automatic relations with explicit user corrections."""

    STATE_VERSION = 1

    def __init__(self, input_dir, relation_report: dict, state_path, visual_suggestions: dict | None = None) -> None:
        self.input_dir = Path(input_dir)
        self.relation_report = relation_report
        self.state_path = Path(state_path)
        self.invoice_parser = InvoiceParser()
        self.items = self._load_items()
        self.items_by_key = {item.key: item for item in self.items}
        self.photo_files = self._load_photo_files()
        self.auto_assignments = self._load_auto_assignments()
        self.purchase_proofs_by_invoice = self._load_purchase_proofs()
        self.visual_suggestions = visual_suggestions or {}
        self.state = self._load_state()

    @classmethod
    def from_paths(cls, input_dir, relation_report_path, state_path, visual_suggestions_path=None):
        report_path = Path(relation_report_path)
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding="utf-8"))
        else:
            report = RelationRecoveryPipeline().run(input_dir, report_path)
        visual = {}
        if visual_suggestions_path:
            suggestion_path = Path(visual_suggestions_path)
            if suggestion_path.exists():
                try:
                    visual = json.loads(suggestion_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    visual = {}
        return cls(input_dir, report, state_path, visual_suggestions=visual)

    def _load_items(self) -> list[ReviewItem]:
        rows = []
        for pdf in sorted(self.input_dir.glob("*.pdf")):
            invoice = self.invoice_parser.parse(str(pdf))
            for item in invoice.items:
                key = f"{invoice.source}::{item.name}"
                rows.append(ReviewItem(
                    key=key,
                    invoice_file=invoice.source,
                    invoice_name=Path(invoice.source).name,
                    item_name=item.name,
                    display_name=friendly_item_name(item.name),
                    invoice_total=float(invoice.total or 0),
                    invoice_date=invoice.date,
                ))
        return rows

    def _load_photo_files(self) -> list[str]:
        rows = [
            row["path"] for row in self.relation_report.get("images", [])
            if row.get("category") == "product_photo_candidate"
        ]
        def natural_key(value: str):
            path = Path(value)
            digits = "".join(ch for ch in path.stem if ch.isdigit())
            return (path.stem.rstrip(digits), int(digits) if digits else 0, path.name)
        return sorted(rows, key=natural_key)

    def _load_auto_assignments(self) -> dict[str, list[str]]:
        mapping = {}
        for match in self.relation_report.get("photo_matches", []):
            key = f'{match["invoice_file"]}::{match["item_name"]}'
            mapping.setdefault(match["photo_file"], []).append(key)
        return mapping

    def _load_purchase_proofs(self) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = {}
        for match in self.relation_report.get("purchase_proof_matches", []):
            mapping.setdefault(match["invoice_file"], []).append(match["screenshot_file"])
        return mapping

    def _empty_state(self) -> dict:
        return {
            "version": self.STATE_VERSION,
            "input_dir": str(self.input_dir),
            "assignments": {},
            "ignored": [],
            "reviewed": [],
        }

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return self._empty_state()
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty_state()
        if state.get("version") != self.STATE_VERSION:
            return self._empty_state()
        state.setdefault("assignments", {})
        state.setdefault("ignored", [])
        state.setdefault("reviewed", [])
        return state

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_copy(self, target_path: str | Path) -> Path:
        """Save a UTF-8 copy of the current review decisions without moving autosave."""
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    def assignment_keys(self, photo_file: str) -> list[str]:
        manual = self.state["assignments"].get(photo_file)
        if manual is not None:
            return [key for key in manual if key in self.items_by_key]
        if photo_file in set(self.state["ignored"]):
            return []
        return [key for key in self.auto_assignments.get(photo_file, []) if key in self.items_by_key]

    def assignment_source(self, photo_file: str) -> str:
        if photo_file in self.state["assignments"]:
            return "manual"
        if photo_file in set(self.state["ignored"]):
            return "ignored"
        if self.auto_assignments.get(photo_file):
            return "auto"
        return "unresolved"

    def set_assignment(self, photo_file: str, item_keys: list[str]) -> None:
        valid = list(dict.fromkeys(key for key in item_keys if key in self.items_by_key))
        self.state["assignments"][photo_file] = valid
        self.state["ignored"] = [x for x in self.state["ignored"] if x != photo_file]
        if photo_file not in self.state["reviewed"]:
            self.state["reviewed"].append(photo_file)
        self.save()

    def ignore(self, photo_file: str) -> None:
        self.state["assignments"].pop(photo_file, None)
        if photo_file not in self.state["ignored"]:
            self.state["ignored"].append(photo_file)
        if photo_file not in self.state["reviewed"]:
            self.state["reviewed"].append(photo_file)
        self.save()

    def clear_manual(self, photo_file: str) -> None:
        self.state["assignments"].pop(photo_file, None)
        self.state["ignored"] = [x for x in self.state["ignored"] if x != photo_file]
        self.state["reviewed"] = [x for x in self.state["reviewed"] if x != photo_file]
        self.save()

    def unresolved_photos(self) -> list[str]:
        return [photo for photo in self.photo_files if self.assignment_source(photo) == "unresolved"]

    def review_progress(self) -> dict:
        sources = [self.assignment_source(photo) for photo in self.photo_files]
        resolved = sum(source != "unresolved" for source in sources)
        coverage = self.photo_item_coverage()
        return {
            "total": len(sources),
            "resolved": resolved,
            "unresolved": len(sources) - resolved,
            "auto": sources.count("auto"),
            "manual": sources.count("manual"),
            "ignored": sources.count("ignored"),
            "covered_items": coverage["covered_items"],
            "total_items": coverage["total_items"],
            "missing_item_keys": coverage["missing_item_keys"],
        }

    def photo_item_coverage(self) -> dict:
        mapping = self.merged_photo_map()
        covered = {key for key, photos in mapping.items() if photos and key in self.items_by_key}
        all_keys = {item.key for item in self.items}
        missing = [item.key for item in self.items if item.key not in covered]
        return {
            "covered_items": len(covered),
            "total_items": len(all_keys),
            "missing_item_keys": missing,
        }

    def merged_photo_map(self) -> dict[str, list[str]]:
        mapping = {}
        for photo in self.photo_files:
            for key in self.assignment_keys(photo):
                mapping.setdefault(key, []).append(photo)
        return mapping

    def purchase_proof_map(self) -> dict[str, list[str]]:
        return RelationRecoveryPipeline.purchase_proof_map(self.relation_report)

    def proof_files_for_item(self, item_key: str) -> list[str]:
        item = self.items_by_key.get(item_key)
        if not item:
            return []
        return list(self.purchase_proofs_by_invoice.get(item.invoice_file, []))

    def first_proof_for_keys(self, item_keys: list[str]) -> str | None:
        for key in item_keys:
            proofs = self.proof_files_for_item(key)
            if proofs:
                return proofs[0]
        return None

    def visual_suggestions_for_photo(self, photo_file: str) -> list[dict]:
        rows = self.visual_suggestions.get("suggestions", {}).get(photo_file, [])
        return [row for row in rows if row.get("item_key") in self.items_by_key]

    def sibling_item_keys(self, item_key: str) -> list[str]:
        item = self.items_by_key.get(item_key)
        if not item:
            return []
        return [row.key for row in self.items if row.invoice_file == item.invoice_file]

    def export_name_map(self) -> dict[str, str]:
        """Map raw invoice item keys to concise names for generated artifacts."""
        return {item.key: item.display_name for item in self.items}

    def export_item_order_map(self) -> dict[str, int]:
        """Order exported items by reviewed product-photo sequence."""
        ordered: list[str] = []
        seen: set[str] = set()
        for photo in self.photo_files:
            for key in self.assignment_keys(photo):
                if key in self.items_by_key and key not in seen:
                    ordered.append(key)
                    seen.add(key)
        for item in self.items:
            if item.key not in seen:
                ordered.append(item.key)
                seen.add(item.key)
        return {key: index for index, key in enumerate(ordered, 1)}

    def export_summary(self) -> dict:
        """Summarize the current batch before final archive export."""
        invoice_totals: dict[str, float] = {}
        for item in self.items:
            invoice_totals[item.invoice_file] = item.invoice_total
        photo_map = self.merged_photo_map()
        purchase_map = self.purchase_proofs_by_invoice
        payment_invoices: set[str] = set()
        progress = self.review_progress()
        return {
            "invoice_count": len(invoice_totals),
            "item_count": len(self.items),
            "photo_covered_items": sum(1 for item in self.items if photo_map.get(item.key)),
            "purchase_proof_covered_items": sum(
                1 for item in self.items if purchase_map.get(item.invoice_file)
            ),
            "payment_covered_items": sum(
                1 for item in self.items if item.invoice_file in payment_invoices
            ),
            "total_amount": round(sum(invoice_totals.values()), 2),
            "unresolved_photos": progress["unresolved"],
        }

    def export_archive(self, output_root) -> list[Path]:
        return ArchivePipeline().run_directory(
            self.input_dir,
            output_root,
            photo_map=self.merged_photo_map(),
            purchase_proof_map=self.purchase_proof_map(),
            name_map=self.export_name_map(),
            item_order_map=self.export_item_order_map(),
        )

    def item_rows(self) -> list[dict]:
        return [asdict(item) for item in self.items]


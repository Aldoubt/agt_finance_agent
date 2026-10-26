"""Behavior tests for real import, user corrections and resumable local batches."""

import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image
import pymupdf

from core.parser.invoice_parser import InvoiceItem, InvoiceResult
from core.parser.screenshot_parser import ScreenshotResult
from core.workbench.batch import BatchSession, money


class BatchBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.sources = self.base / "downloads"
        self.sources.mkdir()
        self.session = BatchSession.create(self.base / "batches", "测试采购")
        self.ocr_patch = patch.object(BatchSession, "_try_ocr", return_value=None)
        self.ocr_patch.start()

    def tearDown(self):
        self.ocr_patch.stop()
        self.temporary.cleanup()

    def image(self, name="IMG_1001.jpg", color="green"):
        path = self.sources / name
        Image.new("RGB", (100, 75), color).save(path)
        return path

    def pdf(self, name="乱码_%F0.PDF", label="SYNTHETIC TEST"):
        path = self.sources / name
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((40, 50), label)
        document.save(str(path))
        document.close()
        return path

    def import_invoice(self):
        path = self.pdf()
        parsed = InvoiceResult(source=str(path), invoice_no="TEST-1", date="2026-10-26", total=200,
                               items=[InvoiceItem(name="连接器", amount=120),
                                      InvoiceItem(name="连接器", amount=80)])
        with patch("core.parser.invoice_parser.InvoiceParser.parse", return_value=parsed):
            result = self.session.import_files([path], kind="invoice")
        self.assertEqual(result["added"], 1)
        return path

    def test_photos_can_arrive_first_and_survive_source_move_and_duplicate_names(self):
        photo = self.image()
        result = self.session.import_files([photo], kind="photo")
        self.assertEqual(result["added"], 1)
        renamed = self.sources / "未命名.jpg"
        shutil.copyfile(photo, renamed)
        result = self.session.import_files([renamed], kind="photo")
        self.assertEqual(result["duplicates"], 1)
        photo.unlink()
        renamed.unlink()
        loaded = BatchSession.load(self.session.path)
        self.assertEqual(loaded.summary()["invoice_count"], 0)
        self.assertEqual(loaded.summary()["asset_count"], 1)
        self.assertTrue(loaded.asset_path(loaded.assets[0]).exists())
        moved = self.base / "moved-batch"
        shutil.move(str(loaded.path), moved)
        self.assertTrue(BatchSession.load(moved).asset_path(loaded.assets[0]).exists())

    def test_same_named_rows_have_distinct_ids_and_confirmed_links_survive_incremental_import(self):
        invoice_source = self.import_invoice()
        first, second = self.session.items
        self.assertNotEqual(first["id"], second["id"])
        self.session.import_files([self.image()], kind="photo")
        photo = next(asset for asset in self.session.assets if asset["kind"] == "photo")
        self.session.set_links(photo["id"], [first["id"], second["id"]])
        self.session.confirm_invoice(self.session.invoices[0]["id"])
        duplicate = self.sources / "another_name.pdf"
        shutil.copyfile(invoice_source, duplicate)
        result = self.session.import_files([duplicate, self.image("later.png", "orange")], kind="auto")
        self.assertEqual(result["duplicates"], 1)
        restored = BatchSession.load(self.session.path)
        self.assertEqual(restored.summary()["total_amount"], "200.00")
        self.assertEqual(restored.summary()["photo_covered_items"], 2)
        self.assertTrue(restored.invoices[0]["confirmed"])
        linked = next(asset for asset in restored.assets if asset["id"] == photo["id"])
        self.assertEqual(linked["item_ids"], [first["id"], second["id"]])

    def test_packages_and_ignored_assets_do_not_count_as_product_photos(self):
        self.import_invoice()
        self.session.import_files([self.image()], kind="package")
        package = self.session.assets[-1]
        self.session.set_links(package["id"], [self.session.items[0]["id"]])
        self.assertEqual(self.session.summary()["photo_covered_items"], 0)
        self.session.set_asset_kind(package["id"], "photo")
        self.assertFalse(package["confirmed"])
        self.session.set_links(package["id"], [self.session.items[0]["id"]])
        self.assertEqual(self.session.summary()["photo_covered_items"], 1)
        self.session.ignore_asset(package["id"])
        self.assertEqual(self.session.summary()["photo_covered_items"], 0)
        invoice_asset = self.session.invoices[0]["asset_id"]
        self.session.ignore_asset(invoice_asset)
        self.assertEqual(self.session.summary()["total_amount"], "0.00")
        self.session.ignore_asset(invoice_asset, False)
        self.assertEqual(self.session.summary()["total_amount"], "200.00")

    def test_reimport_repairs_missing_or_changed_managed_bytes_without_losing_review(self):
        self.import_invoice()
        source = self.image()
        self.session.import_files([source], kind="photo")
        photo = self.session.assets[-1]
        selected = [item["id"] for item in self.session.items]
        self.session.set_links(photo["id"], selected)
        managed = self.session.asset_path(photo)
        for broken in ("missing", "changed"):
            if broken == "missing":
                managed.unlink()
            else:
                managed.write_bytes(b"changed after import")
            result = self.session.import_files([source])
            self.assertEqual(result["restored"], 1)
            self.assertEqual(result["added"], 0)
            self.assertEqual(result["errors"], [])
            self.assertEqual(managed.read_bytes(), source.read_bytes())
            loaded = BatchSession.load(self.session.path)
            restored = next(asset for asset in loaded.assets if asset["id"] == photo["id"])
            self.assertTrue(restored["confirmed"])
            self.assertEqual(restored["item_ids"], selected)
            self.assertEqual(restored["kind"], "photo")

    def test_unread_amount_stays_unknown_and_manual_correction_requires_balanced_invoice(self):
        result = self.session.import_files([self.pdf()], kind="invoice")
        self.assertEqual(result["added"], 1)
        invoice = self.session.invoices[0]
        self.assertIsNone(invoice["total"])
        self.assertEqual(self.session.summary()["unknown_amount_invoices"], 1)
        item = self.session.add_item(invoice["id"], "手动补充的商品", "12.34")
        self.session.update_invoice(invoice["id"], total="12.35")
        with self.assertRaisesRegex(ValueError, "不一致"):
            self.session.confirm_invoice(invoice["id"])
        self.session.update_item(item["id"], amount="12.35")
        self.session.confirm_invoice(invoice["id"])
        self.assertTrue(invoice["confirmed"])
        self.session.update_item(item["id"], name="核对后的名称")
        self.assertFalse(invoice["confirmed"])
        self.assertEqual(item["raw_name"], "")

    def test_exact_cent_tax_addition_and_manual_edits_never_silently_round(self):
        source = self.pdf()
        parsed = InvoiceResult(source=str(source), total=0.3,
                               items=[InvoiceItem(name="含税商品", amount=0.1, tax_amount=0.2)])
        with patch("core.parser.invoice_parser.InvoiceParser.parse", return_value=parsed):
            self.session.import_files([source], kind="invoice")
        invoice, item = self.session.invoices[0], self.session.items[0]
        self.assertEqual(invoice["total"], "0.30")
        self.assertEqual(item["amount"], "0.30")
        self.session.confirm_invoice(invoice["id"])
        for change in (
            lambda: self.session.update_invoice(invoice["id"], total="1.005"),
            lambda: self.session.update_item(item["id"], amount="1.005"),
            lambda: self.session.add_item(invoice["id"], "不应新增", "1.005"),
        ):
            with self.assertRaisesRegex(ValueError, "精确到分"):
                change()
        self.assertTrue(invoice["confirmed"])
        self.assertEqual(invoice["total"], "0.30")
        self.assertEqual(item["amount"], "0.30")
        self.assertEqual(len(self.session.items), 1)
        self.assertEqual(money("1.2300"), "1.23")
        self.assertEqual(money("-0.00"), "0.00")

    def test_late_manual_items_refresh_recommendations_but_preserve_human_drafts(self):
        first_source = self.image("order-first.png", "blue")
        ocr = ScreenshotResult(source_file=str(first_source), category="purchase_proof",
                               amount=10.00, text="订单信息 交易成功 ST-LINK V2 实付款 10.00")
        with patch.object(BatchSession, "_try_ocr", return_value=ocr):
            self.session.import_files([first_source], kind="auto")
        first = self.session.assets[0]
        self.assertEqual(first["kind"], "purchase_proof")
        self.assertEqual(first["suggested_item_ids"], [])
        self.session.import_files([self.pdf()], kind="invoice")
        invoice = self.session.invoices[0]
        self.session.update_invoice(invoice["id"], total="10.00")
        item = self.session.add_item(invoice["id"], "尚未核对的名称", "10.00")
        self.assertEqual(first["suggested_item_ids"], [])  # Same amount alone is insufficient.
        self.session.update_item(item["id"], name="ST-LINK V2")
        self.session.confirm_invoice(invoice["id"])
        self.assertEqual(first["suggested_item_ids"], [item["id"]])
        self.assertFalse(first["confirmed"])
        self.session.set_links(first["id"], [item["id"]], confirmed=False)

        with patch.object(BatchSession, "_try_ocr", return_value=ocr):
            self.session.import_files([self.image("order-second.png", "red")], kind="auto")
        second = self.session.assets[-1]
        extra = self.session.add_item(invoice["id"], "另附连接线", "0.00")
        self.assertEqual(second["suggested_item_ids"], [item["id"], extra["id"]])
        self.assertEqual(first["suggested_item_ids"], [item["id"]])
        self.session.remove_item(extra["id"])
        self.assertEqual(second["suggested_item_ids"], [item["id"]])
        self.session.ignore_asset(invoice["asset_id"])
        self.assertEqual(second["suggested_item_ids"], [])
        self.assertEqual(first["suggested_item_ids"], [item["id"]])
        self.session.ignore_asset(invoice["asset_id"], False)
        self.assertEqual(second["suggested_item_ids"], [item["id"]])
        self.session.set_links(second["id"], [item["id"]])
        self.session.update_item(item["id"], name="人工选定的商品名")
        self.assertEqual(second["item_ids"], [item["id"]])
        self.assertTrue(second["confirmed"])
        loaded = BatchSession.load(self.session.path)
        loaded.update_invoice(invoice["id"], supplier="补录商家")
        self.assertEqual(loaded.assets[0]["suggested_item_ids"], [item["id"]])
        self.assertFalse(loaded.assets[0]["confirmed"])

    def test_one_damaged_file_does_not_lose_other_materials(self):
        bad = self.sources / "broken.pdf"
        bad.write_bytes(b"not a PDF")
        result = self.session.import_files([bad, self.image()], kind="auto")
        self.assertEqual(result["added"], 2)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(len(BatchSession.load(self.session.path).assets), 2)
        self.assertIsNone(self.session.invoices[0]["total"])

    def test_atomic_save_failure_keeps_previous_progress(self):
        original = (self.session.path / "batch.json").read_text(encoding="utf-8")
        with patch("core.workbench.batch.os.replace", side_effect=OSError("simulated disk error")):
            with self.assertRaises(OSError):
                self.session.rename("未能保存的新名称")
        self.assertEqual((self.session.path / "batch.json").read_text(encoding="utf-8"), original)
        self.assertEqual(list(self.session.path.glob(".batch-*.tmp")), [])
        self.assertEqual(BatchSession.load(self.session.path).data["name"], "测试采购")

    def test_nonfinite_amounts_and_escaping_asset_paths_are_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity", float("nan")):
            with self.assertRaises(ValueError):
                money(value)
        self.session.import_files([self.image()], kind="photo")
        self.session.assets[0]["path"] = "../../outside.png"
        self.session.save()
        with self.assertRaisesRegex(ValueError, "超出"):
            BatchSession.load(self.session.path)

    def test_demo_uses_real_files_and_retains_exact_total_and_multiple_product_invoice(self):
        demo = BatchSession.create_demo(self.base / "batches")
        self.assertTrue(demo.data["demo"])
        self.assertEqual(demo.summary()["total_amount"], "258.00")
        self.assertEqual(len(demo.invoices), 2)
        self.assertEqual(len(demo.items), 3)
        self.assertEqual(demo.summary()["photo_covered_items"], 0)
        self.assertTrue(all(demo.asset_path(asset).exists() for asset in demo.assets))
        for invoice in demo.invoices:
            demo.confirm_invoice(invoice["id"])
        for asset in demo.assets:
            if asset["kind"] in {"photo", "purchase_proof"}:
                demo.set_links(asset["id"], asset["suggested_item_ids"])
        self.assertEqual(demo.summary()["photo_covered_items"], 3)
        self.assertEqual(demo.summary()["purchase_proof_covered_items"], 2)
        self.assertEqual(demo.summary()["payment_proof_covered_items"], 0)
        before = [row["id"] for row in demo.items]
        demo.move_invoice(demo.invoices[1]["id"], -1)
        self.assertEqual([row["id"] for row in demo.items], [before[2], before[0], before[1]])
        self.assertEqual(demo.summary()["total_amount"], "258.00")


if __name__ == "__main__":
    unittest.main()

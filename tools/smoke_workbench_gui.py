"""Exercise the real Tk workbench and real demo export on an available display.

Example on Linux: DISPLAY=:97 python tools/smoke_workbench_gui.py --screenshots /tmp/agt-finance-ui-qa
This is a developer smoke check, not part of the normal user's workflow.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from tkinter import messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agt_finance_agent.workbench_gui import EXCEL_HEADERS, WorkbenchApp


def run(screenshot_dir: Path | None = None, workspace_root: Path | None = None):
    if workspace_root is not None:
        workspace_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agt-workbench-smoke-", dir=workspace_root) as temporary:
        directory = Path(temporary)
        root = tk.Tk()
        errors = []
        root.report_callback_exception = lambda kind, value, _tb: errors.append(f"{kind.__name__}: {value}")
        original_error = messagebox.showerror
        messagebox.showerror = lambda title, message, **_kwargs: errors.append(f"{title}: {message}")
        app = WorkbenchApp(root, workspace_root=directory / "batches")
        root.geometry("1000x760+20+20")

        def settle(seconds=0.25):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                root.update()
                time.sleep(0.015)
            if errors:
                raise AssertionError("; ".join(errors))

        def idle(timeout=30):
            deadline = time.monotonic() + timeout
            while app.busy and time.monotonic() < deadline:
                settle(0.05)
            assert not app.busy, "Background work did not finish"
            settle()

        def screenshot(name):
            if screenshot_dir is None:
                return
            try:
                from PIL import ImageGrab
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                settle(0.5)
                box = (root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height())
                ImageGrab.grab(bbox=box).save(screenshot_dir / name)
            except (ImportError, OSError) as exc:
                print(f"SCREENSHOT UNAVAILABLE: {name}: {exc}")

        def assert_footer_visible():
            settle()
            assert app.next_button.winfo_ismapped(), "Primary action is hidden"
            bottom = app.next_button.winfo_rooty() + app.next_button.winfo_height()
            assert bottom <= root.winfo_rooty() + root.winfo_height(), "Primary action is below window"
            right = app.next_button.winfo_rootx() + app.next_button.winfo_width()
            assert right <= root.winfo_rootx() + root.winfo_width(), "Primary action is outside window"

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        try:
            settle()
            assert app.step == 0
            screenshot("01-home-1000x760.png")
            app.start_demo()
            idle()
            assert app.step == 1
            assert app.session.summary()["total_amount"] == "258.00"
            screenshot("02-materials-1000x760.png")
            app.next_step()
            settle()
            assert app.step == 2
            screenshot("03-invoice-1000x760.png")
            app.move_invoice(1)
            settle()
            app.move_invoice(-1)
            settle()
            app._invoice_form["supplier"].set("示例供应商（人工核对）")
            app.next_step()
            settle()
            app.next_step()
            settle()
            assert app.step == 3
            assert all(invoice["confirmed"] for invoice in app.session.invoices)
            screenshot("04-photo-1000x760.png")
            root.geometry("900x650+20+20")
            settle()
            assert_footer_visible()
            screenshot("05-photo-900x650.png")
            for _ in range(8):
                if app.step != 3:
                    break
                app.next_step()
                idle()
            assert app.step == 4
            idle()
            assert not app._preview_errors, app._preview_errors
            assert app.session.summary()["photo_covered_items"] == 3
            assert_footer_visible()
            screenshot("06-preview-900x650.png")
            notebooks = [widget for widget in descendants(app.page.content) if isinstance(widget, ttk.Notebook)]
            assert len(notebooks) == 1
            notebooks[0].select(2)
            screenshot("07-excel-900x650.png")
            app._output_root = directory / "output"
            app._output_root.mkdir()
            app.export_batch()
            idle()
            assert app.step == 5
            target = app._output_root / "258.00"
            assert len(list(target.glob("*.pdf"))) == 2
            assert sorted(path.suffix for path in target.iterdir()) == [".docx", ".pdf", ".pdf", ".xlsx"]
            from openpyxl import load_workbook
            book = load_workbook(target / "采购统计.xlsx", data_only=True)
            sheet = book["采购统计"]
            assert tuple(cell.value for cell in sheet[1]) == EXCEL_HEADERS
            assert [sheet.cell(row, 1).value for row in (2, 3, 4)] == [1, 2, 3]
            assert sheet.cell(2, 8).value == sheet.cell(3, 8).value
            assert sheet.cell(sheet.max_row, 1).value == "总金额"
            assert sheet.cell(sheet.max_row, 3).value == 258
            screenshot("08-complete-900x650.png")
            print("PASS: real Tk home/import/invoice/multi-item-photo/preview/export workflow")
            print("PASS: 1000x760 and 900x650 primary actions visible; async preview/export; no Tk callback errors")
            print("PASS: real 258.00 archive, 2 PDFs + DOCX + XLSX, original 8 Excel columns")
        finally:
            messagebox.showerror = original_error
            try:
                root.after_cancel(app._poll_id)
                root.destroy()
            except tk.TclError:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot-dir", "--screenshots", dest="screenshot_dir", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    arguments = parser.parse_args()
    run(arguments.screenshot_dir, arguments.workspace_root)

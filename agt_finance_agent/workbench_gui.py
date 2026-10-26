"""Guided, local desktop workflow for procurement evidence and reimbursement files.

All financial and archive decisions belong to BatchSession / ExportPlan.  This
module only presents their state, collects explicit corrections and runs slow
work outside Tk's event loop.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont
from typing import Callable

from PIL import Image, ImageOps

from core.review.photo_review_gui import ZoomImagePane
from core.workbench.batch import BatchSession


KIND_LABELS = {
    "invoice": "发票",
    "photo": "商品实物图",
    "purchase_proof": "购买凭证 / 淘宝截图",
    "payment_proof": "支付凭证",
    "package": "只有快递外包装",
    "unknown": "待分类",
}
LINKABLE_KINDS = {"photo", "purchase_proof", "payment_proof"}
EXCEL_HEADERS = (
    "序号", "商品名称", "金额", "发票是否存在", "实物图是否存在",
    "购买凭证是否存在", "支付凭证是否存在", "发票文件",
)
BG = "#f3f6f7"
PANEL = "#ffffff"
INK = "#24343d"
MUTED = "#5c6d76"
GREEN = "#185e48"
WARN = "#875d1d"


def _text(value, fallback="") -> str:
    return fallback if value is None else str(value)


def _money(value, empty="待核对") -> str:
    if value is None or value == "":
        return empty
    try:
        return f"{Decimal(str(value)):.2f}"
    except (InvalidOperation, ValueError):
        return str(value)


def _decimal_input(value: str, label: str) -> str | None:
    value = value.strip().replace("，", ",").replace(",", "")
    if not value:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{label}请填写数字，例如 58.00。") from exc
    if not number.is_finite():
        raise ValueError(f"{label}请填写有效金额。")
    try:
        if number != number.quantize(Decimal("0.01")):
            raise ValueError(f"{label}最多保留两位小数。")
    except InvalidOperation as exc:
        raise ValueError(f"{label}数值过长，请检查是否多输了数字。") from exc
    return f"{number:.2f}"


class ScrollPage(ttk.Frame):
    """One resizeable document area; action buttons remain outside this scroller."""

    def __init__(self, master):
        super().__init__(master, style="Page.TFrame")
        self.canvas = tk.Canvas(self, background=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.content = ttk.Frame(self.canvas, padding=(20, 18), style="Page.TFrame")
        self.window = self.canvas.create_window(0, 0, anchor="nw", window=self.content)
        self.content.bind("<Configure>", self._content_changed)
        self.canvas.bind("<Configure>", self._canvas_changed)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda _e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda _e: self.canvas.yview_scroll(3, "units"))

    def _content_changed(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _canvas_changed(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)

    def _wheel(self, event):
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def clear(self):
        for widget in self.content.winfo_children():
            widget.destroy()
        self.canvas.yview_moveto(0)


class DocumentPreview(ZoomImagePane):
    """Reuse the existing zoom/pan viewer with asynchronous PDF/image decoding."""

    def __init__(self, master, title="原始材料预览"):
        super().__init__(master, title)
        self._preview_queue = queue.Queue()
        self._preview_token = 0
        self._document_path: Path | None = None
        self._page_index = 0
        self._page_count = 1
        self._fit_id = None
        self._preview_body = self.winfo_children()[1]
        self._page_bar = ttk.Frame(self)
        self._page_bar.pack(fill="x", pady=(0, 4), before=self._preview_body)
        self._previous_page = ttk.Button(self._page_bar, text="上一页", command=lambda: self.turn_page(-1))
        self._previous_page.pack(side="left", padx=(0, 5))
        self._page_label = ttk.Label(self._page_bar, text="")
        self._page_label.pack(side="left", padx=2)
        self._next_page = ttk.Button(self._page_bar, text="下一页", command=lambda: self.turn_page(1))
        self._next_page.pack(side="left", padx=(5, 0))
        self.canvas.configure(height=340)
        self.canvas.bind("<Button-4>", lambda _event: self.zoom(1.15))
        self.canvas.bind("<Button-5>", lambda _event: self.zoom(1 / 1.15))
        self._poll_id = self.after(80, self._poll_preview)
        self.bind("<Destroy>", self._destroyed, add="+")

    def _destroyed(self, event):
        if event.widget is self:
            self._preview_token += 1
            try:
                self.after_cancel(self._poll_id)
                if self._fit_id is not None:
                    self.after_cancel(self._fit_id)
            except tk.TclError:
                pass

    def load_document(self, path: str | Path | None):
        self._document_path = Path(path) if path else None
        self._page_index = 0
        self._page_count = 1
        self._start_preview()

    def turn_page(self, offset: int):
        target = self._page_index + offset
        if 0 <= target < self._page_count:
            self._page_index = target
            self._start_preview()

    def _start_preview(self):
        self._preview_token += 1
        token, path, page = self._preview_token, self._document_path, self._page_index
        if path and path.suffix.lower() == ".pdf":
            self._page_bar.pack(fill="x", pady=(0, 4), before=self._preview_body)
        else:
            self._page_bar.pack_forget()
        self._page_label.configure(text="读取中…")
        self._previous_page.configure(state="disabled")
        self._next_page.configure(state="disabled")
        self.clear("正在读取预览…" if path else "选择一份材料查看原件")
        if path is None:
            self._page_label.configure(text="")
            return

        def worker():
            try:
                if path.suffix.lower() == ".pdf":
                    import fitz

                    with fitz.open(path) as document:
                        count = len(document)
                        if not count:
                            raise ValueError("PDF 没有页面")
                        source = document[min(page, count - 1)]
                        scale = min(1.7, 1600 / max(source.rect.width, source.rect.height, 1))
                        pixmap = source.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                else:
                    with Image.open(path) as source:
                        image = ImageOps.exif_transpose(source).convert("RGB")
                        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                        image = image.copy()
                    count = 1
                self._preview_queue.put((token, image, count, None))
            except Exception as exc:
                self._preview_queue.put((token, None, 1, exc))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_preview(self):
        try:
            while True:
                token, image, count, error = self._preview_queue.get_nowait()
                if token != self._preview_token:
                    continue
                if error:
                    self.clear("暂时无法预览这份材料。请检查文件是否完整，或重新放入原文件。")
                    self._page_label.configure(text="预览不可用")
                    continue
                self._base_image = image
                self._page_count = count
                self._path = str(self._document_path)
                self._page_label.configure(text=f"{self._page_index + 1}/{count}")
                self._previous_page.configure(state="normal" if self._page_index else "disabled")
                self._next_page.configure(state="normal" if self._page_index + 1 < count else "disabled")
                self._fit_id = self.after_idle(self.fit)
        except queue.Empty:
            pass
        self._poll_id = self.after(80, self._poll_preview)

    def zoom(self, factor):
        if self._base_image is not None:
            ceiling = min(8.0, 4096 / max(self._base_image.size))
            self._scale = max(0.08, min(self._scale * factor, ceiling))
            self._render(center=False)


class WorkbenchApp:
    def __init__(self, root: tk.Tk, workspace_root=None):
        self.root = root
        self.workspace_root = workspace_root
        self.session: BatchSession | None = None
        self.step = 0
        self.busy = False
        self.close_when_idle = False
        self._job_queue = queue.Queue()
        self._disabled_widgets = []
        self._selected_invoice = None
        self._selected_asset = None
        self._invoice_list_expanded = False
        self._asset_list_expanded = False
        self._invoice_form = {}
        self._item_form = []
        self._photo_vars = {}
        self._photo_touched = False
        self._photo_asset_id = None
        self._undo_links = None
        self._preview = {}
        self._preview_errors = []
        self._preview_warnings = []
        self._last_import_errors = []
        self._failed_import_paths = []
        self._last_import_kind = "auto"
        self._output_root = None
        self.root.title("AGT 采购材料整理")
        self.root.geometry("1180x800")
        self.root.minsize(900, 650)
        self._style()
        self._shell()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<MouseWheel>", self._scroll_at_pointer, add="+")
        self.root.bind("<Button-4>", self._scroll_at_pointer, add="+")
        self.root.bind("<Button-5>", self._scroll_at_pointer, add="+")
        self._poll_id = self.root.after(100, self._poll_jobs)
        self.show_home()

    def _style(self):
        available = {family.casefold(): family for family in tkfont.families(self.root)}
        candidates = ("Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei", "PingFang SC")
        family = next((available[candidate.casefold()] for candidate in candidates if candidate.casefold() in available), tkfont.nametofont("TkDefaultFont", self.root).actual("family"))
        self.root.option_add("*Font", (family, 10))
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", font=(family, 10), foreground=INK)
        style.configure("TFrame", background=PANEL)
        style.configure("Page.TFrame", background=BG)
        style.configure("TLabel", background=PANEL, foreground=INK)
        style.configure("Page.TLabel", background=BG)
        style.configure("Muted.TLabel", foreground=MUTED, background=PANEL)
        style.configure("PageMuted.TLabel", foreground=MUTED, background=BG)
        style.configure("Title.TLabel", font=(family, 19), background=BG)
        style.configure("Heading.TLabel", font=(family, 12), background=PANEL)
        style.configure("Brand.TLabel", font=(family, 15), background=PANEL)
        style.configure("Warn.TLabel", foreground=WARN, background=PANEL)
        style.configure("PageWarn.TLabel", foreground=WARN, background=BG)
        style.configure("TButton", padding=(12, 7))
        style.configure("Primary.TButton", background=GREEN, foreground="white", padding=(18, 9))
        style.map("Primary.TButton", background=[("disabled", "#becbc5"), ("active", "#124b39")], foreground=[("disabled", "#61766b")])
        style.configure("Step.TLabel", padding=(12, 8), foreground=MUTED, background=BG)
        style.configure("ActiveStep.TLabel", padding=(12, 8), foreground=GREEN, background="#e3f0e8")
        style.configure("Treeview", rowheight=30, background=PANEL, fieldbackground=PANEL)
        style.configure("Treeview.Heading", padding=(5, 6), font=(family, 10))
        style.configure("TCheckbutton", background=PANEL, padding=(3, 5))
        self.root.configure(background=BG)

    def _shell(self):
        chrome = ttk.Frame(self.root, padding=(20, 14))
        chrome.pack(fill="x")
        ttk.Label(chrome, text="AGT 采购材料整理", style="Brand.TLabel").pack(side="left")
        self.batch_label = ttk.Label(chrome, text="", style="Muted.TLabel")
        self.batch_label.pack(side="left", padx=20)
        self.home_button = ttk.Button(chrome, text="返回首页", command=self.go_home)
        self.home_button.pack(side="right")
        self.rename_button = ttk.Button(chrome, text="批次名称", command=self.rename_batch)
        self.rename_button.pack(side="right", padx=8)
        self.step_frame = ttk.Frame(self.root, style="Page.TFrame", padding=(20, 6))
        self.step_frame.pack(fill="x")
        self.step_labels = []
        for index, title in enumerate(("放入材料", "核对清单", "确认照片", "预览导出"), 1):
            label = ttk.Label(self.step_frame, text=f"{index}  {title}", style="Step.TLabel")
            label.pack(side="left", fill="x", expand=True)
            self.step_labels.append(label)
        self.page = ScrollPage(self.root)
        self.page.pack(fill="both", expand=True)
        self.footer = ttk.Frame(self.root, padding=(20, 12))
        self.footer.pack(fill="x")
        self.footer_hint = ttk.Label(self.footer, text="", style="Muted.TLabel")
        self.footer_hint.pack(side="left")
        self.next_button = ttk.Button(self.footer, style="Primary.TButton", command=self.next_step)
        self.next_button.pack(side="right")
        self.back_button = ttk.Button(self.footer, text="上一步", command=self.previous_step)
        self.back_button.pack(side="right", padx=10)
        self.status_frame = ttk.Frame(self.root, padding=(20, 7), style="Page.TFrame")
        self.status_frame.pack(fill="x")
        self.status_var = tk.StringVar(value="文件保存在本机；原始文件不需要改名。")
        self.status_label = ttk.Label(self.status_frame, textvariable=self.status_var, style="PageMuted.TLabel", wraplength=850)
        self.status_label.pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(self.status_frame, mode="indeterminate", length=150)

    def status(self, message):
        self.status_var.set(str(message))

    def _scroll_at_pointer(self, event):
        widget = event.widget
        while widget is not None:
            if isinstance(widget, (DocumentPreview, ttk.Treeview)):
                return
            if isinstance(widget, ScrollPage):
                direction = -1 if getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0 else 1
                widget.canvas.yview_scroll(direction * 2, "units")
                return "break"
            widget = getattr(widget, "master", None)

    def _heading(self, title, description):
        ttk.Label(self.page.content, text=title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.page.content, text=description, style="PageMuted.TLabel", wraplength=920).pack(anchor="w", pady=(6, 18))

    def _panel(self, parent=None, **pack_kwargs):
        frame = ttk.Frame(parent or self.page.content, padding=16)
        frame.pack(fill="x", pady=(0, 12), **pack_kwargs)
        return frame

    def _tree(self, parent, columns, labels, widths, height=5, selectmode="browse"):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=height, selectmode=selectmode)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        for column, label, width in zip(columns, labels, widths):
            tree.heading(column, text=label)
            tree.column(column, width=width, minwidth=min(width, 70), stretch=column not in {"sequence", "amount", "status"})
        return tree

    def _friendly_error(self, error):
        message = str(error).strip() or "操作未完成，请检查材料后重试。"
        if self.session is not None:
            message = message.replace(str(self.session.path), "本批次材料")
        return message[:1500]

    def _error(self, title, error):
        self.status(self._friendly_error(error))
        messagebox.showerror(title, self._friendly_error(error), parent=self.root)

    def _walk_controls(self, widget):
        for child in widget.winfo_children():
            if isinstance(child, (ttk.Button, ttk.Entry, ttk.Combobox, ttk.Checkbutton)):
                yield child
            yield from self._walk_controls(child)

    def _set_busy(self, busy):
        self.busy = busy
        if busy:
            self._disabled_widgets = []
            for widget in self._walk_controls(self.root):
                self._disabled_widgets.append((widget, widget.state()))
                widget.state(["disabled"])
            self.progress.pack(side="right", padx=(12, 0))
            self.progress.start(12)
        else:
            for widget, prior in self._disabled_widgets:
                try:
                    widget.state(["!disabled"])
                    if "disabled" in prior:
                        widget.state(["disabled"])
                except tk.TclError:
                    pass
            self._disabled_widgets.clear()
            self.progress.stop()
            self.progress.pack_forget()
            self._update_navigation()

    @staticmethod
    def _progress_text(args, kwargs):
        if kwargs.get("message"):
            return str(kwargs["message"])
        if args and isinstance(args[0], dict):
            value = args[0]
            return str(value.get("message") or value.get("status") or "正在处理材料…")
        for value in reversed(args):
            if isinstance(value, str):
                return value
        return "正在处理材料…"

    def _background(self, label, work: Callable, on_done: Callable, on_error: Callable | None = None):
        if self.busy:
            return
        self.status(label)
        self._set_busy(True)

        def progress(*args, **kwargs):
            self._job_queue.put(("progress", self._progress_text(args, kwargs), None, None))

        def worker():
            try:
                result = work(progress)
                self._job_queue.put(("done", result, on_done, on_error))
            except Exception as exc:
                self._job_queue.put(("error", exc, on_done, on_error))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_jobs(self):
        try:
            while True:
                kind, payload, on_done, on_error = self._job_queue.get_nowait()
                if kind == "progress":
                    self.status(payload)
                    continue
                self._set_busy(False)
                if kind == "done":
                    try:
                        on_done(payload)
                    except Exception as exc:
                        self._error("显示结果时遇到问题", exc)
                elif on_error:
                    on_error(payload)
                else:
                    self._error("这次操作没有完成", payload)
                if self.close_when_idle:
                    self.close_when_idle = False
                    self.close()
                    return
        except queue.Empty:
            pass
        self._poll_id = self.root.after(100, self._poll_jobs)

    def _update_navigation(self):
        active = self.session is not None and 1 <= self.step <= 4
        self.batch_label.configure(text=self.session.data.get("name", "采购批次") if self.session and self.step else "")
        self.rename_button.configure(state="normal" if self.session and self.step and not self.busy else "disabled")
        self.home_button.configure(state="normal" if self.step and not self.busy else "disabled")
        for index, label in enumerate(self.step_labels, 1):
            label.configure(style="ActiveStep.TLabel" if index == self.step else "Step.TLabel")
        self.footer_hint.configure(text=f"第 {self.step} 步，共 4 步 · 修改保存在本批次" if active else "")
        if active:
            self.back_button.pack(side="right", padx=10)
            self.next_button.pack(side="right")
            self.back_button.configure(text="返回首页" if self.step == 1 else "上一步")
            label = {1: "下一步：核对清单", 2: "确认本票并继续", 3: "确认关联并继续", 4: "生成归档文件夹"}[self.step]
            if self.step == 2 and not self._active_invoices():
                label = "先确认照片"
            if self.step == 3:
                asset = self._asset(self._selected_asset)
                if not asset or asset.get("ignored") or asset.get("kind") not in LINKABLE_KINDS:
                    label = "保留待补，继续预览"
            self.next_button.configure(text=label, state="disabled" if self.busy or (self.step == 4 and self._preview_errors) else "normal")
        else:
            self.next_button.pack_forget()
            self.back_button.pack_forget()

    def _asset(self, asset_id):
        return next((asset for asset in self.session.assets if asset["id"] == asset_id), None) if self.session else None

    def _invoice(self, invoice_id):
        return next((invoice for invoice in self.session.invoices if invoice["id"] == invoice_id), None) if self.session else None

    def _ordered_items(self):
        if self.session is None:
            return []
        return [item for invoice in self._active_invoices() for item in self.session.items if item.get("invoice_id") == invoice["id"]]

    def _active_invoices(self):
        if self.session is None:
            return []
        return [invoice for invoice in self.session.invoices if not (self._asset(invoice.get("asset_id")) or {}).get("ignored")]

    def _flush_current(self):
        if self.step == 2 and self._invoice_form:
            return self._save_invoice_editor(confirm=False)
        if self.step == 3:
            return self._resolve_photo_draft()
        return True

    def show_home(self):
        self.step = 0
        self._invoice_form = {}
        self._item_form = []
        self._photo_vars = {}
        self.page.clear()
        self._heading("把发票和收货照片整理成报销材料", "不用提前改文件名。把这一批材料放进来，跟着四步完成整理。")
        overview = self._panel()
        overview.columnconfigure(0, weight=1)
        overview.columnconfigure(1, weight=1)
        left, right = ttk.Frame(overview), ttk.Frame(overview)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 22))
        right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(left, text="准备这些材料", style="Heading.TLabel").pack(anchor="w")
        for text in ("邮箱下载的发票 PDF：乱码文件名也可以", "收货后的商品照片：一张图可以有多件商品", "淘宝订单 / 支付截图：有就一起放入，没有可稍后补"):
            ttk.Label(left, text=text, wraplength=470).pack(anchor="w", pady=(12, 0))
        ttk.Label(right, text="得到一个整理好的文件夹", style="Heading.TLabel").pack(anchor="w")
        for text in ("按确认顺序命名的发票 PDF", "实物图.docx：商品照片与购买凭证", "采购统计.xlsx：沿用原有 8 列格式"):
            ttk.Label(right, text=text, wraplength=430).pack(anchor="w", pady=(12, 0))
        actions = ttk.Frame(overview)
        actions.grid(row=1, column=0, columnspan=2, sticky="w", pady=(22, 0))
        ttk.Button(actions, text="开始整理", style="Primary.TButton", command=self.begin_new).pack(side="left")
        ttk.Button(actions, text="查看示例", command=self.start_demo).pack(side="left", padx=10)
        history = self._panel()
        ttk.Label(history, text="继续上次的批次", style="Heading.TLabel").pack(anchor="w", pady=(0, 8))
        self.history_tree = self._tree(history, ("name", "materials", "items", "updated"), ("批次名称", "材料", "商品", "最近保存"), (330, 90, 90, 210), height=4)
        self._history_rows = {}
        try:
            batches = BatchSession.list_batches(self.workspace_root)
        except Exception as exc:
            batches = []
            self.status("暂时无法读取历史批次：" + self._friendly_error(exc))
        for index, batch in enumerate(batches):
            key = f"batch-{index}"
            self._history_rows[key] = batch
            self.history_tree.insert("", "end", iid=key, values=(batch.get("name", "采购批次"), batch.get("asset_count", 0), batch.get("item_count", 0), batch.get("updated_at", "")))
        self.history_tree.bind("<Double-1>", lambda _event: self.continue_batch())
        ttk.Button(history, text="继续选中的批次", command=self.continue_batch).pack(anchor="e", pady=(9, 0))
        if not batches:
            ttk.Label(history, text="还没有保存的批次。点击“开始整理”即可。", style="Muted.TLabel").pack(anchor="w")
        self._update_navigation()

    def go_home(self):
        if not self.busy and self._flush_current():
            self.show_home()

    def begin_new(self):
        if self.busy:
            return
        try:
            self.session = BatchSession.create(workspace_root=self.workspace_root)
            self._selected_invoice = self._selected_asset = None
            self._invoice_list_expanded = self._asset_list_expanded = False
            self._undo_links = None
            self.show_step(1, flush=False)
            self.status("批次已创建。可以先放入照片，发票之后再补。")
        except Exception as exc:
            self._error("无法创建批次", exc)

    def start_demo(self):
        if self.busy:
            return

        def done(session):
            self.session = session
            self._selected_invoice = self._selected_asset = None
            self._invoice_list_expanded = self._asset_list_expanded = False
            self._undo_links = None
            self.show_step(1, flush=False)
            self.status("已载入虚构示例材料。可以完成实际归档操作；示例不含私人财务数据。")

        self._background("正在准备示例材料…", lambda _progress: BatchSession.create_demo(workspace_root=self.workspace_root), done)

    def continue_batch(self):
        if self.busy:
            return
        selected = self.history_tree.selection()
        if not selected:
            self.status("请先在列表中选择一个批次。")
            return
        try:
            batch = self._history_rows[selected[0]]
            self.session = BatchSession.load(batch["path"])
            self._selected_invoice = self._selected_asset = None
            self._invoice_list_expanded = self._asset_list_expanded = False
            self._undo_links = None
            self.show_step(max(1, min(4, int(self.session.data.get("step", 1)))), flush=False)
            self.status("已恢复批次和已确认的人工关联。")
        except Exception as exc:
            self._error("无法打开这个批次", exc)

    def rename_batch(self):
        if self.session is None or self.busy:
            return
        name = simpledialog.askstring("批次名称", "给这批材料起一个便于查找的名称：", initialvalue=self.session.data.get("name", ""), parent=self.root)
        if name and name.strip():
            try:
                self.session.rename(name.strip())
                self._update_navigation()
            except Exception as exc:
                self._error("名称未保存", exc)

    def show_step(self, step, flush=True):
        if self.busy or self.session is None:
            return
        if flush and not self._flush_current():
            return
        target_step = max(1, min(4, int(step)))
        try:
            self.session.set_step(target_step)
        except Exception as exc:
            self._error("进度未保存", exc)
            return
        self.step = target_step
        self._invoice_form = {}
        self._item_form = []
        self._photo_vars = {}
        self._photo_touched = False
        self._photo_asset_id = None
        self.page.clear()
        {1: self._build_import, 2: self._build_invoice_review, 3: self._build_photo_review, 4: self._build_export_preview}[self.step]()
        self._update_navigation()

    def previous_step(self):
        if self.step <= 1:
            self.go_home()
        else:
            self.show_step(self.step - 1)

    def next_step(self):
        if self.busy or self.session is None:
            return
        if self.step == 1:
            self.show_step(2)
        elif self.step == 2:
            if not self._active_invoices():
                self.show_step(3)
            elif self._save_invoice_editor(confirm=not (self._asset((self._invoice(self._selected_invoice) or {}).get("asset_id")) or {}).get("ignored")):
                pending = next((invoice for invoice in self._active_invoices() if not invoice.get("confirmed")), None)
                if pending:
                    self._selected_invoice = pending["id"]
                    self.show_step(2, flush=False)
                    self.status("上一张发票已确认，请核对下一张。")
                else:
                    self.show_step(3, flush=False)
        elif self.step == 3:
            self._confirm_photo(advance=True)
        elif self.step == 4:
            self.export_batch()

    def _build_import(self):
        self._heading("先把这一批材料放进来", "从邮箱下载发票、从手机传入收货照片。原文件名可以保留，材料也可以分几次补齐。")
        choices = self._panel()
        for label, kind in (("选择发票 PDF…", "invoice"), ("选择商品照片…", "photo"), ("选择淘宝 / 支付截图…", "purchase_proof")):
            ttk.Button(choices, text=label, command=lambda value=kind: self.choose_files(value)).pack(side="left", padx=(0, 10))
        ttk.Button(choices, text="导入混合文件夹…", command=self.choose_folder).pack(side="left")
        materials = self._panel()
        ttk.Label(materials, text=f"已放入 {len(self.session.assets)} 份材料", style="Heading.TLabel").pack(anchor="w", pady=(0, 8))
        self.import_tree = self._tree(materials, ("name", "kind", "status"), ("原文件名", "材料类型", "处理状态"), (480, 210, 230), height=7)
        for asset in self.session.assets:
            status = "已忽略" if asset.get("ignored") else "需人工核对" if asset.get("error") else "已放入"
            self.import_tree.insert("", "end", iid=asset["id"], values=(asset.get("original_name", ""), KIND_LABELS.get(asset.get("kind"), "待分类"), status))
        self.import_tree.bind("<Double-1>", self._open_imported_asset)
        if not self.session.assets:
            ttk.Label(materials, text="还没有材料。先选择上面一种材料即可开始。", style="Muted.TLabel").pack(anchor="w", pady=10)
        ttk.Label(materials, text="识别不到的内容可以手工填写；支付截图的类型可在“确认照片”中修改。", style="Muted.TLabel", wraplength=900).pack(anchor="w", pady=(10, 0))
        if self._last_import_errors:
            errors = self._panel()
            ttk.Label(errors, text="这些材料还需处理；已导入的内容和原件仍保留", style="Warn.TLabel").pack(anchor="w")
            for error in self._last_import_errors[:8]:
                name = Path(str(error.get("path", error.get("file", "文件")))).name if isinstance(error, dict) else "文件"
                detail = error.get("message", error.get("error", "无法读取")) if isinstance(error, dict) else str(error)
                ttk.Label(errors, text=f"{name}：{detail}", wraplength=850).pack(anchor="w", pady=3)
            if self._failed_import_paths:
                ttk.Button(errors, text="重试未能读取的文件", command=self.retry_import).pack(anchor="w", pady=(8, 0))
            ttk.Label(errors, text="识别不完整的发票可以到下一步手工补齐。", style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

    def choose_files(self, kind):
        if self.busy:
            return
        types = [("PDF 发票", "*.pdf *.PDF")] if kind == "invoice" else [("图片", "*.jpg *.jpeg *.png *.webp *.bmp"), ("所有文件", "*.*")]
        paths = filedialog.askopenfilenames(parent=self.root, title="选择这一批的材料（可多选，不用改名）", filetypes=types)
        if paths:
            self.import_paths(paths, kind)

    def choose_folder(self):
        folder = filedialog.askdirectory(parent=self.root, title="选择这一批材料所在的文件夹")
        if folder:
            self.import_paths([folder], "auto")

    def import_paths(self, paths, kind="auto"):
        if self.session is None or self.busy:
            return
        self._last_import_kind = kind

        def done(result):
            result = result or {}
            self._last_import_errors = result.get("errors", []) or []
            self._failed_import_paths = result.get("failed_paths", []) or []
            self.show_step(1, flush=False)
            count = lambda value: len(value) if isinstance(value, (list, tuple, dict)) else int(value or 0)
            self.status(f"已放入 {count(result.get('added'))} 份；恢复 {count(result.get('restored'))} 份；重复材料 {count(result.get('duplicates'))} 份；需处理事项 {len(self._last_import_errors)} 条。")

        self._background("正在复制材料并识别可读内容…", lambda progress: self.session.import_files(list(paths), kind=kind, progress=progress), done)

    def retry_import(self):
        paths = list(self._failed_import_paths)
        if paths:
            self.import_paths(paths, self._last_import_kind)
        else:
            self.choose_folder()

    def _open_imported_asset(self, _event=None):
        if self.busy or not self.import_tree.selection():
            return
        asset = self._asset(self.import_tree.selection()[0])
        if asset.get("kind") == "invoice":
            invoice = next((invoice for invoice in self.session.invoices if invoice.get("asset_id") == asset["id"]), None)
            self._selected_invoice = invoice["id"] if invoice else None
            self.show_step(2)
        else:
            self._selected_asset = asset["id"]
            self.show_step(3)

    def _build_invoice_review(self):
        self._heading("核对商品名称和金额", "选择一张发票，对照右侧原件修改内容。每张核对完成后，点击底部“确认本票并继续”。")
        if not self.session.invoices:
            empty = self._panel()
            ttk.Label(empty, text="还没有发票。可以返回放入 PDF，也可以先整理照片，稍后补发票。", wraplength=850).pack(anchor="w")
            ttk.Button(empty, text="返回放入发票", command=lambda: self.show_step(1)).pack(anchor="w", pady=(12, 0))
            return
        panel = self._panel()
        quick = ttk.Frame(panel)
        quick.pack(fill="x")
        self.invoice_current_var = tk.StringVar()
        ttk.Label(quick, textvariable=self.invoice_current_var, wraplength=470).pack(side="left", fill="x", expand=True)
        self.invoice_previous_button = ttk.Button(quick, text="上一张", command=lambda: self._navigate_invoice(-1))
        self.invoice_previous_button.pack(side="left", padx=(8, 4))
        self.invoice_next_button = ttk.Button(quick, text="下一张", command=lambda: self._navigate_invoice(1))
        self.invoice_next_button.pack(side="left", padx=(0, 8))
        self.invoice_expand_button = ttk.Button(quick, text="展开全部发票", command=self._toggle_invoice_manager)
        self.invoice_expand_button.pack(side="right")
        self.invoice_manager_body = ttk.Frame(panel)
        self.invoice_tree = self._tree(self.invoice_manager_body, ("sequence", "name", "products", "amount", "status"), ("顺序", "原发票文件", "商品", "票面合计", "核对状态"), (65, 310, 300, 110, 110), height=4)
        for index, invoice in enumerate(self.session.invoices, 1):
            asset = self._asset(invoice.get("asset_id")) or {}
            products = "、".join(item.get("name", "") for item in self.session.items if item.get("invoice_id") == invoice["id"])
            self.invoice_tree.insert("", "end", iid=invoice["id"], values=(index, asset.get("original_name", ""), products or "待补商品明细", _money(invoice.get("total")), "已忽略" if asset.get("ignored") else "已确认" if invoice.get("confirmed") else "待核对"))
        actions = ttk.Frame(self.invoice_manager_body)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="这张发票上移", command=lambda: self.move_invoice(-1)).pack(side="left")
        ttk.Button(actions, text="这张发票下移", command=lambda: self.move_invoice(1)).pack(side="left", padx=8)
        ttk.Button(actions, text="不使用 / 恢复这张发票", command=self.toggle_invoice_ignore).pack(side="left", padx=8)
        ttk.Label(self.invoice_manager_body, text="这里的顺序决定导出发票及商品清单的顺序。", style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        if not self._invoice(self._selected_invoice):
            candidate = next((invoice for invoice in self.session.invoices if not invoice.get("confirmed")), self.session.invoices[0])
            self._selected_invoice = candidate["id"]
        self.invoice_tree.selection_set(self._selected_invoice)
        self.invoice_tree.see(self._selected_invoice)
        self.invoice_tree.bind("<<TreeviewSelect>>", self._invoice_selected)
        self._set_invoice_manager_visibility()
        self._refresh_invoice_navigation()
        self.invoice_editor_host = ttk.Frame(self.page.content, style="Page.TFrame")
        self.invoice_editor_host.pack(fill="both", expand=True)
        self._render_invoice_editor()

    def _invoice_selected(self, _event=None):
        if self.busy or not self.invoice_tree.selection():
            return
        selected = self.invoice_tree.selection()[0]
        if selected == self._selected_invoice:
            return
        if not self._save_invoice_editor(confirm=False):
            self.invoice_tree.selection_set(self._selected_invoice)
            return
        self._selected_invoice = selected
        self._render_invoice_editor()
        self._refresh_invoice_navigation()

    def _set_invoice_manager_visibility(self):
        if self._invoice_list_expanded:
            self.invoice_manager_body.pack(fill="both", expand=True, pady=(12, 0))
        else:
            self.invoice_manager_body.pack_forget()
        self.invoice_expand_button.configure(text="收起全部发票" if self._invoice_list_expanded else "展开全部发票")

    def _toggle_invoice_manager(self):
        self._invoice_list_expanded = not self._invoice_list_expanded
        self._set_invoice_manager_visibility()

    def _refresh_invoice_navigation(self):
        invoice = self._invoice(self._selected_invoice)
        if not invoice:
            return
        index = self.session.invoices.index(invoice)
        asset = self._asset(invoice.get("asset_id")) or {}
        state = "已忽略" if asset.get("ignored") else "已确认" if invoice.get("confirmed") else "待核对"
        self.invoice_current_var.set(f"当前发票 {index + 1}/{len(self.session.invoices)} · {state} · {_money(invoice.get('total'))} 元\n{asset.get('original_name', '')}")
        self.invoice_previous_button.configure(state="normal" if index else "disabled")
        self.invoice_next_button.configure(state="normal" if index + 1 < len(self.session.invoices) else "disabled")

    def _navigate_invoice(self, offset):
        invoice = self._invoice(self._selected_invoice)
        if self.busy or not invoice or not self._save_invoice_editor():
            return
        index = self.session.invoices.index(invoice) + offset
        if 0 <= index < len(self.session.invoices):
            self._selected_invoice = self.session.invoices[index]["id"]
            self.invoice_tree.selection_set(self._selected_invoice)
            self.invoice_tree.see(self._selected_invoice)
            self._render_invoice_editor()
            self._refresh_invoice_navigation()

    def _render_invoice_editor(self):
        for child in self.invoice_editor_host.winfo_children():
            child.destroy()
        invoice = self._invoice(self._selected_invoice)
        self._invoice_form = {}
        self._item_form = []
        if not invoice:
            return
        self.invoice_editor_host.columnconfigure(0, weight=1, uniform="invoice")
        self.invoice_editor_host.columnconfigure(1, weight=1, uniform="invoice")
        editor = ttk.Frame(self.invoice_editor_host, padding=15)
        editor.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        preview = DocumentPreview(self.invoice_editor_host, "发票原件 · 可翻页、缩放")
        preview.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self.invoice_preview = preview
        asset = self._asset(invoice.get("asset_id"))
        if asset:
            preview.load_document(self.session.asset_path(asset))
        ttk.Label(editor, text="票面信息", style="Heading.TLabel").pack(anchor="w")
        fields = ttk.Frame(editor)
        fields.pack(fill="x", pady=(8, 10))
        fields.columnconfigure(0, weight=1)
        fields.columnconfigure(1, weight=1)
        for index, (key, label) in enumerate((("invoice_no", "发票号码"), ("date", "开票日期"), ("supplier", "销售方"), ("order_no", "订单号（可留空）"), ("total", "票面价税合计（元）"))):
            cell = ttk.Frame(fields)
            cell.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0, 8), pady=4)
            ttk.Label(cell, text=label, style="Muted.TLabel").pack(anchor="w")
            variable = tk.StringVar(value=_text(invoice.get(key)))
            self._invoice_form[key] = variable
            ttk.Entry(cell, textvariable=variable).pack(fill="x", pady=(3, 0))
        if asset and asset.get("error"):
            ttk.Label(editor, text="部分内容未能自动识别。请对照原件手工补齐名称和金额。", style="Warn.TLabel", wraplength=410).pack(anchor="w", pady=(0, 8))
        ttk.Label(editor, text="商品明细（含税金额）", style="Heading.TLabel").pack(anchor="w", pady=(4, 6))
        self.item_rows_host = ttk.Frame(editor)
        self.item_rows_host.pack(fill="x")
        for item in self.session.items:
            if item.get("invoice_id") != invoice["id"]:
                continue
            row = ttk.Frame(self.item_rows_host)
            row.pack(fill="x", pady=4)
            name_var = tk.StringVar(value=item.get("name", ""))
            amount_var = tk.StringVar(value=_text(item.get("amount")))
            self._item_form.append((item["id"], name_var, amount_var))
            ttk.Entry(row, textvariable=name_var).pack(side="left", fill="x", expand=True)
            ttk.Entry(row, textvariable=amount_var, width=9).pack(side="left", padx=6)
            ttk.Button(row, text="移除", width=4, command=lambda item_id=item["id"]: self.remove_item(item_id)).pack(side="left")
            amount_var.trace_add("write", lambda *_args: self._refresh_amount_check())
        add_row = ttk.Frame(editor)
        add_row.pack(fill="x", pady=(8, 0))
        ttk.Button(add_row, text="＋ 添加商品明细", command=self.add_item).pack(side="left")
        ttk.Button(add_row, text="保存当前修改", command=lambda: self._save_invoice_editor(confirm=False, notify=True)).pack(side="right")
        self.amount_check_var = tk.StringVar()
        ttk.Label(editor, textvariable=self.amount_check_var, style="Warn.TLabel", wraplength=410).pack(anchor="w", pady=(12, 0))
        self._invoice_form["total"].trace_add("write", lambda *_args: self._refresh_amount_check())
        self._refresh_amount_check()

    def _refresh_amount_check(self):
        if not self._invoice_form or not hasattr(self, "amount_check_var"):
            return
        try:
            total = _decimal_input(self._invoice_form["total"].get(), "票面合计")
            amounts = [_decimal_input(var.get(), "商品金额") for _, _, var in self._item_form]
            if total is None or not amounts or any(amount is None for amount in amounts):
                self.amount_check_var.set("请补齐票面合计和每项商品金额；无法识别的明细可以添加。")
            else:
                subtotal = sum((Decimal(value) for value in amounts), Decimal("0"))
                gap = subtotal - Decimal(total)
                self.amount_check_var.set(f"明细合计 {subtotal:.2f} 元 · 票面合计 {total} 元" + (" · 一致" if not gap else f" · 相差 {abs(gap):.2f} 元，请核对"))
        except ValueError as exc:
            self.amount_check_var.set(str(exc))

    def _save_invoice_editor(self, confirm=False, notify=False):
        invoice = self._invoice(self._selected_invoice)
        if not invoice or not self._invoice_form:
            return True
        try:
            fields = {key: var.get().strip() for key, var in self._invoice_form.items()}
            fields["total"] = _decimal_input(fields["total"], "票面价税合计")
            item_changes = [(item_id, name_var.get().strip(), _decimal_input(amount_var.get(), "商品金额")) for item_id, name_var, amount_var in self._item_form]
            if confirm:
                if fields["total"] is None:
                    raise ValueError("请填写这张发票的价税合计。")
                if not item_changes:
                    raise ValueError("这张发票尚无商品明细，请点击“添加商品明细”。")
                if any(not name or amount is None for _, name, amount in item_changes):
                    raise ValueError("请补齐每项商品的名称和含税金额。")
                subtotal = sum((Decimal(amount) for _, _, amount in item_changes), Decimal("0"))
                if subtotal != Decimal(fields["total"]):
                    raise ValueError(f"商品合计 {subtotal:.2f} 元，与票面合计 {fields['total']} 元不一致，请核对后再确认。")
            changed = {key: value for key, value in fields.items() if _text(invoice.get(key)) != _text(value)}
            if changed:
                self.session.update_invoice(invoice["id"], **changed)
            for item_id, name, amount in item_changes:
                item = next(item for item in self.session.items if item["id"] == item_id)
                updates = {}
                if item.get("name") != name:
                    updates["name"] = name
                if _text(item.get("amount")) != _text(amount):
                    updates["amount"] = amount
                if updates:
                    self.session.update_item(item_id, **updates)
            if confirm:
                self.session.confirm_invoice(invoice["id"], True)
            self._refresh_invoice_tree()
            self._refresh_invoice_navigation()
            if notify:
                self.status("当前修改已保存。核对无误后，点击“确认本票并继续”。")
            return True
        except Exception as exc:
            self._error("请先核对当前发票", exc)
            return False

    def _refresh_invoice_tree(self):
        if not hasattr(self, "invoice_tree") or not self.invoice_tree.winfo_exists():
            return
        for index, invoice in enumerate(self.session.invoices, 1):
            if not self.invoice_tree.exists(invoice["id"]):
                continue
            asset = self._asset(invoice.get("asset_id")) or {}
            products = "、".join(item.get("name", "") for item in self.session.items if item.get("invoice_id") == invoice["id"])
            self.invoice_tree.item(invoice["id"], values=(index, asset.get("original_name", ""), products or "待补商品明细", _money(invoice.get("total")), "已忽略" if asset.get("ignored") else "已确认" if invoice.get("confirmed") else "待核对"))

    def add_item(self):
        if not self._save_invoice_editor():
            return
        try:
            self.session.add_item(self._selected_invoice, name="", amount=None)
            self._render_invoice_editor()
            self.status("已增加一项商品，请填写名称和含税金额。")
        except Exception as exc:
            self._error("未能添加商品", exc)

    def remove_item(self, item_id):
        if not self._save_invoice_editor():
            return
        try:
            self.session.remove_item(item_id)
            self._render_invoice_editor()
            self._refresh_invoice_tree()
            self.status("已移除这条录入明细；原发票文件仍保留。")
        except Exception as exc:
            self._error("未能移除商品", exc)

    def move_invoice(self, offset):
        if self.busy or not self._save_invoice_editor():
            return
        try:
            self.session.move_invoice(self._selected_invoice, offset)
            self.show_step(2, flush=False)
            self.status("发票顺序已保存；导出的发票、Word 和 Excel 会同步调整。")
        except Exception as exc:
            self._error("顺序未调整", exc)

    def toggle_invoice_ignore(self):
        if self.busy or not self._save_invoice_editor():
            return
        invoice = self._invoice(self._selected_invoice)
        asset = self._asset(invoice.get("asset_id")) if invoice else None
        if asset:
            try:
                self.session.ignore_asset(asset["id"], not asset.get("ignored", False))
                self.show_step(2, flush=False)
                self.status("发票使用状态已保存；原件仍保留在本批次。")
            except Exception as exc:
                self._error("发票状态未修改", exc)

    def _build_photo_review(self):
        self._heading("确认照片和凭证对应哪些商品", "选择一份材料，核对类型，再勾选对应商品。一张照片或截图可以关联多个商品。")
        candidates = [asset for asset in self.session.assets if asset.get("kind") != "invoice"]
        if not candidates:
            panel = self._panel()
            ttk.Label(panel, text="还没有照片或截图。可以返回补材料，也可以先预览归档并保留缺失状态。", wraplength=850).pack(anchor="w")
            ttk.Button(panel, text="返回补材料", command=lambda: self.show_step(1)).pack(anchor="w", pady=(12, 0))
            return
        table_panel = self._panel()
        quick = ttk.Frame(table_panel)
        quick.pack(fill="x")
        self.asset_current_var = tk.StringVar()
        ttk.Label(quick, textvariable=self.asset_current_var, wraplength=430).pack(side="left", fill="x", expand=True)
        self.asset_previous_button = ttk.Button(quick, text="上一份", command=lambda: self._navigate_asset(-1))
        self.asset_previous_button.pack(side="left", padx=(8, 4))
        self.asset_next_button = ttk.Button(quick, text="下一份", command=lambda: self._navigate_asset(1))
        self.asset_next_button.pack(side="left", padx=(0, 8))
        self.asset_expand_button = ttk.Button(quick, text="展开全部材料", command=self._toggle_asset_manager)
        self.asset_expand_button.pack(side="right")
        self.asset_manager_body = ttk.Frame(table_panel)
        self.asset_tree = self._tree(self.asset_manager_body, ("name", "kind", "links", "status"), ("原文件名", "材料类型", "关联商品", "状态"), (310, 210, 310, 120), height=4)
        items_by_id = {item["id"]: item for item in self.session.items}
        for asset in candidates:
            names = "、".join(items_by_id[item_id].get("name", "") for item_id in asset.get("item_ids", []) if item_id in items_by_id)
            state = "已忽略" if asset.get("ignored") else "已确认" if asset.get("confirmed") else "待确认"
            self.asset_tree.insert("", "end", iid=asset["id"], values=(asset.get("original_name", ""), KIND_LABELS.get(asset.get("kind"), "待分类"), names or "未关联", state))
        if not any(asset["id"] == self._selected_asset for asset in candidates):
            candidate = next((asset for asset in candidates if not asset.get("confirmed") and not asset.get("ignored")), candidates[0])
            self._selected_asset = candidate["id"]
        self.asset_tree.selection_set(self._selected_asset)
        self.asset_tree.see(self._selected_asset)
        self.asset_tree.bind("<<TreeviewSelect>>", self._asset_selected)
        actions = ttk.Frame(self.asset_manager_body)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="下一份待确认材料", command=self.next_unconfirmed_asset).pack(side="left")
        ttk.Button(actions, text="撤销上一次关联", command=self.undo_last_links, state="normal" if self._undo_links else "disabled").pack(side="left", padx=8)
        ttk.Button(actions, text="照片稍后补，先预览", command=lambda: self.show_step(4)).pack(side="right")
        self._set_asset_manager_visibility()
        self._refresh_asset_navigation()
        self.photo_editor_host = ttk.Frame(self.page.content, style="Page.TFrame")
        self.photo_editor_host.pack(fill="both", expand=True)
        self._render_photo_editor()

    def _asset_selected(self, _event=None):
        if self.busy or not self.asset_tree.selection():
            return
        selected = self.asset_tree.selection()[0]
        if selected == self._selected_asset:
            return
        if not self._resolve_photo_draft():
            self.asset_tree.selection_set(self._selected_asset)
            return
        self._selected_asset = selected
        self._render_photo_editor()
        self._refresh_asset_navigation()
        self._update_navigation()

    def _set_asset_manager_visibility(self):
        if self._asset_list_expanded:
            self.asset_manager_body.pack(fill="both", expand=True, pady=(12, 0))
        else:
            self.asset_manager_body.pack_forget()
        self.asset_expand_button.configure(text="收起全部材料" if self._asset_list_expanded else "展开全部材料")

    def _toggle_asset_manager(self):
        self._asset_list_expanded = not self._asset_list_expanded
        self._set_asset_manager_visibility()

    def _refresh_asset_navigation(self):
        candidates = [asset for asset in self.session.assets if asset.get("kind") != "invoice"]
        asset = self._asset(self._selected_asset)
        if not asset or asset not in candidates:
            return
        index = candidates.index(asset)
        state = "已忽略" if asset.get("ignored") else "已确认" if asset.get("confirmed") else "待确认"
        self.asset_current_var.set(f"当前材料 {index + 1}/{len(candidates)} · {state}\n{asset.get('original_name', '')}")
        self.asset_previous_button.configure(state="normal" if index else "disabled")
        self.asset_next_button.configure(state="normal" if index + 1 < len(candidates) else "disabled")

    def _navigate_asset(self, offset):
        if self.busy or not self._resolve_photo_draft():
            return
        candidates = [asset for asset in self.session.assets if asset.get("kind") != "invoice"]
        asset = self._asset(self._selected_asset)
        if not asset or asset not in candidates:
            return
        index = candidates.index(asset) + offset
        if 0 <= index < len(candidates):
            self._selected_asset = candidates[index]["id"]
            self.asset_tree.selection_set(self._selected_asset)
            self.asset_tree.see(self._selected_asset)
            self._render_photo_editor()
            self._refresh_asset_navigation()
            self._update_navigation()

    def _render_photo_editor(self):
        for child in self.photo_editor_host.winfo_children():
            child.destroy()
        self._photo_vars = {}
        self._photo_touched = False
        self._photo_asset_id = self._selected_asset
        asset = self._asset(self._selected_asset)
        if not asset:
            return
        self.photo_editor_host.columnconfigure(0, weight=1, uniform="photo")
        self.photo_editor_host.columnconfigure(1, weight=1, uniform="photo")
        preview = DocumentPreview(self.photo_editor_host, "材料原图 · 滚轮缩放、拖动查看")
        preview.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        preview.load_document(self.session.asset_path(asset))
        self.photo_preview = preview
        form = ttk.Frame(self.photo_editor_host, padding=15)
        form.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        ttk.Label(form, text=asset.get("original_name", ""), style="Heading.TLabel", wraplength=440).pack(anchor="w")
        type_row = ttk.Frame(form)
        type_row.pack(fill="x", pady=(10, 12))
        ttk.Label(type_row, text="材料类型").pack(side="left", padx=(0, 10))
        self.kind_var = tk.StringVar(value=KIND_LABELS.get(asset.get("kind"), "待分类"))
        combo = ttk.Combobox(type_row, textvariable=self.kind_var, values=list(KIND_LABELS.values()), state="readonly", width=22)
        combo.pack(side="left", fill="x", expand=True)
        combo.bind("<<ComboboxSelected>>", self._change_asset_kind)
        if asset.get("kind") == "package":
            ttk.Label(form, text="这张照片只有快递外包装。\n暂未展示商品，可补拍后放入，或先保存这份材料。", style="Warn.TLabel", wraplength=420).pack(anchor="w", pady=8)
            ttk.Button(form, text="返回放入补拍照片", command=lambda: self.show_step(1)).pack(anchor="w", pady=8)
        elif asset.get("kind") not in LINKABLE_KINDS:
            ttk.Label(form, text="先将上面的类型改为实物图、购买凭证或支付凭证，再确认商品关联。", style="Warn.TLabel", wraplength=420).pack(anchor="w", pady=8)
        if asset.get("ignored"):
            ttk.Label(form, text="这份材料已忽略，导出时不会使用。", style="Warn.TLabel", wraplength=420).pack(anchor="w", pady=8)
        ttk.Label(form, text="这份材料对应哪些商品？", style="Heading.TLabel").pack(anchor="w", pady=(8, 5))
        suggested = asset.get("suggested_item_ids", [])
        selected = set(asset.get("item_ids", []) if asset.get("confirmed") or asset.get("item_ids") else suggested)
        if suggested and not asset.get("confirmed"):
            ttk.Label(form, text="已勾选识别建议，请对照原图确认。", style="Muted.TLabel").pack(anchor="w", pady=(0, 5))
        checks = ScrollPage(form)
        checks.canvas.configure(height=min(220, max(80, len(self._ordered_items()) * 35 + 12)), background=PANEL)
        checks.content.configure(style="TFrame", padding=(2, 4))
        checks.pack(fill="both", expand=True)
        for index, item in enumerate(self._ordered_items(), 1):
            var = tk.BooleanVar(value=item["id"] in selected)
            self._photo_vars[item["id"]] = var
            label = f"{index}. {item.get('name') or '未命名商品'}  ·  {_money(item.get('amount'))} 元"
            check = ttk.Checkbutton(checks.content, text=label, variable=var, command=self._photo_changed)
            check.pack(anchor="w", fill="x")
            if asset.get("kind") not in LINKABLE_KINDS or asset.get("ignored"):
                check.state(["disabled"])
        if not self.session.items:
            ttk.Label(checks.content, text="先补齐发票商品明细，再回来关联材料。", wraplength=380).pack(anchor="w", pady=8)
            ttk.Button(checks.content, text="去核对商品清单", command=lambda: self.show_step(2)).pack(anchor="w")
        controls = ttk.Frame(form)
        controls.pack(fill="x", pady=(10, 0))
        ttk.Button(controls, text="恢复使用" if asset.get("ignored") else "忽略这份材料", command=self.toggle_ignore).pack(side="left")
        ttk.Button(controls, text="撤销关联", command=self.undo_last_links, state="normal" if self._undo_links else "disabled").pack(side="left", padx=5)
        ttk.Button(controls, text="稍后补，先预览", command=lambda: self.show_step(4)).pack(side="right")
        self.photo_save_label = ttk.Label(form, text="修改关联后，点击底部“确认关联并继续”。", style="Muted.TLabel", wraplength=420)
        self.photo_save_label.pack(anchor="w", pady=(8, 0))

    def _photo_changed(self):
        self._photo_touched = True
        self.photo_save_label.configure(text="当前勾选尚未确认；切换材料时会询问如何保存。")

    def _selected_item_ids(self):
        return [item_id for item_id, var in self._photo_vars.items() if var.get()]

    def _resolve_photo_draft(self):
        if not self._photo_touched:
            return True
        choice = messagebox.askyesnocancel("保存当前材料关联", "当前勾选尚未确认。\n\n选择“是”保存并使用这些关联；\n选择“否”放弃本次勾选；\n选择“取消”留在当前页面。", parent=self.root)
        if choice is None:
            return False
        if choice:
            return self._confirm_photo(advance=False)
        self._photo_touched = False
        return True

    def _confirm_photo(self, advance=True):
        asset = self._asset(self._selected_asset)
        if not asset or asset.get("ignored") or asset.get("kind") not in LINKABLE_KINDS:
            if advance:
                if not self._resolve_photo_draft():
                    return False
                self.show_step(4, flush=False)
            return True
        try:
            old = (asset["id"], list(asset.get("item_ids", []) if asset.get("confirmed") else asset.get("suggested_item_ids", [])), bool(asset.get("confirmed")))
            selected = self._selected_item_ids()
            self.session.set_links(asset["id"], selected, confirmed=True)
            self._undo_links = old
            self._photo_touched = False
            self.status("材料关联已确认并保存。" if selected else "这份材料已确认暂不关联商品，缺失项仍会如实显示。")
            if advance:
                pending = next((row for row in self.session.assets if row.get("kind") in LINKABLE_KINDS and not row.get("ignored") and not row.get("confirmed") and row["id"] != asset["id"]), None)
                if pending:
                    self._selected_asset = pending["id"]
                    self.show_step(3, flush=False)
                else:
                    self.show_step(4, flush=False)
            return True
        except Exception as exc:
            self._error("材料关联未保存", exc)
            return False

    def next_unconfirmed_asset(self):
        if not self._resolve_photo_draft():
            return
        candidates = [asset for asset in self.session.assets if asset.get("kind") != "invoice" and not asset.get("ignored") and not asset.get("confirmed")]
        pending = next((asset for asset in candidates if asset["id"] != self._selected_asset), None)
        if pending:
            self._selected_asset = pending["id"]
            self.show_step(3, flush=False)
        else:
            self.status("没有其他待确认材料。可以预览归档，或回到上一步补材料。")

    def _change_asset_kind(self, _event=None):
        asset = self._asset(self._selected_asset)
        if not asset or not self._resolve_photo_draft():
            if asset:
                self.kind_var.set(KIND_LABELS.get(asset.get("kind"), "待分类"))
            return
        kind = next((key for key, value in KIND_LABELS.items() if value == self.kind_var.get()), "unknown")
        try:
            self.session.set_asset_kind(asset["id"], kind)
            self.show_step(2 if kind == "invoice" else 3, flush=False)
            self.status("材料类型已修改并保存。")
        except Exception as exc:
            self.kind_var.set(KIND_LABELS.get(asset.get("kind"), "待分类"))
            self._error("材料类型未修改", exc)

    def toggle_ignore(self):
        if not self._resolve_photo_draft():
            return
        asset = self._asset(self._selected_asset)
        if asset:
            try:
                self.session.ignore_asset(asset["id"], not asset.get("ignored", False))
                self.show_step(3, flush=False)
            except Exception as exc:
                self._error("材料状态未修改", exc)

    def undo_last_links(self):
        if not self._undo_links or not self._resolve_photo_draft():
            return
        asset_id, item_ids, confirmed = self._undo_links
        try:
            self.session.set_links(asset_id, item_ids, confirmed=confirmed)
            self._undo_links = None
            self._selected_asset = asset_id
            self.show_step(3, flush=False)
            self.status("已撤销上一次关联，并保存恢复后的结果。")
        except Exception as exc:
            self._error("未能撤销关联", exc)

    def _build_export_preview(self):
        self._heading("导出前再看一眼", "检查发票顺序、Word 内容和原格式 Excel。缺少照片或截图可以保留提示；金额与原文件必须核对一致。")
        self.preview_host = ttk.Frame(self.page.content, style="Page.TFrame")
        self.preview_host.pack(fill="both", expand=True)
        ttk.Label(self.preview_host, text="正在检查材料并生成预览…", style="PageMuted.TLabel").pack(anchor="w")
        self._preview_errors = [{"message": "预览检查尚未完成"}]

        def work(_progress):
            try:
                plan = self.session.build_export_plan()
                return plan.to_dict(), [], getattr(plan, "warnings", [])
            except ValueError as exc:
                if hasattr(exc, "preview"):
                    return exc.preview or {}, getattr(exc, "errors", [{"message": str(exc)}]), getattr(exc, "warnings", [])
                raise

        def done(result):
            self._preview, self._preview_errors, self._preview_warnings = result
            self._render_export_preview()
            self._update_navigation()
            self.status("预览已更新。" if not self._preview_errors else "还有需要修复的内容，点击问题或返回对应步骤修改。")

        self._background("正在检查原件、金额和归档顺序…", work, done)

    def _problem_text(self, problem):
        return self._friendly_error(problem.get("message", "需要核对材料") if isinstance(problem, dict) else problem)

    def _render_export_preview(self):
        for widget in self.preview_host.winfo_children():
            widget.destroy()
        data = self._preview or {}
        invoices, items = data.get("invoices", []), data.get("items", [])
        total = _money(data.get("total"))
        summary = self._panel(self.preview_host)
        ttk.Label(summary, text=f"归档文件夹：{total}/   ·   {len(invoices)} 张发票   ·   {len(items)} 项商品", style="Heading.TLabel", wraplength=900).pack(anchor="w")
        if self._preview_errors:
            panel = self._panel(self.preview_host)
            ttk.Label(panel, text="先修复这些内容，再生成正式归档", style="Warn.TLabel").pack(anchor="w", pady=(0, 8))
            self.problem_tree = self._tree(panel, ("message",), ("需要处理的问题（双击可返回修改）",), (900,), height=min(4, max(1, len(self._preview_errors))))
            for index, error in enumerate(self._preview_errors):
                self.problem_tree.insert("", "end", iid=str(index), values=(self._problem_text(error),))
            self.problem_tree.bind("<Double-1>", self._open_problem)
            controls = ttk.Frame(panel)
            controls.pack(fill="x", pady=(8, 0))
            ttk.Button(controls, text="返回核对清单", command=lambda: self.show_step(2)).pack(side="left")
            ttk.Button(controls, text="返回补原文件", command=lambda: self.show_step(1)).pack(side="left", padx=8)
        notebook_panel = self._panel(self.preview_host)
        notebook = ttk.Notebook(notebook_panel)
        notebook.pack(fill="both", expand=True)
        files_page, word_page, excel_page = (ttk.Frame(notebook, padding=10) for _ in range(3))
        notebook.add(files_page, text="归档文件")
        notebook.add(word_page, text="Word 内容顺序")
        notebook.add(excel_page, text="Excel 原格式清单")
        file_tree = self._tree(files_page, ("sequence", "filename", "amount"), ("顺序", "导出文件名", "发票金额"), (70, 700, 120), height=6)
        for invoice in invoices:
            file_tree.insert("", "end", values=(invoice.get("sequence", ""), invoice.get("filename", "待核对发票"), _money(invoice.get("total"))))
        file_tree.insert("", "end", values=("", "实物图.docx", ""))
        file_tree.insert("", "end", values=("", "采购统计.xlsx", ""))
        ttk.Label(word_page, text="商品序号与 Excel 一致；购买凭证和支付凭证一并放入 Word。", style="Muted.TLabel", wraplength=880).pack(anchor="w", pady=(0, 8))
        word_tree = self._tree(word_page, ("sequence", "name", "photos", "orders", "payments"), ("商品序号", "商品名称", "实物图", "购买凭证", "支付凭证"), (90, 460, 110, 110, 110), height=6)
        for item in items:
            word_tree.insert("", "end", values=(item.get("sequence", ""), item.get("name", ""), f"{len(item.get('photo_ids', []))} 张" if item.get("photo_ids") else "待补", f"{len(item.get('purchase_proof_ids', []))} 张" if item.get("purchase_proof_ids") else "未提供", f"{len(item.get('payment_proof_ids', []))} 张" if item.get("payment_proof_ids") else "未提供"))
        ttk.Label(excel_page, text="工作表：采购统计 · 保留现有 8 列及原顺序 · 可横向滚动查看", style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        excel_tree = self._tree(excel_page, tuple(f"col{i}" for i in range(8)), EXCEL_HEADERS, (65, 240, 100, 130, 140, 150, 150, 430), height=6)
        for source_row in data.get("excel_rows", []):
            row = list(source_row)
            if len(row) == 8:
                row[2] = _money(row[2])
                excel_tree.insert("", "end", values=row)
        excel_tree.insert("", "end", values=("总金额", "", total, "", "", "", "", ""))
        warnings = list(self._preview_warnings or data.get("warnings", []))
        if warnings:
            panel = self._panel(self.preview_host)
            ttk.Label(panel, text="材料提示（允许保留缺失状态）", style="Warn.TLabel").pack(anchor="w", pady=(0, 6))
            warning_tree = self._tree(panel, ("message",), ("缺失或待确认的材料",), (900,), height=min(3, len(warnings)))
            for warning in warnings:
                warning_tree.insert("", "end", values=(self._problem_text(warning),))
        output = self._panel(self.preview_host)
        ttk.Label(output, text="保存到哪里", style="Heading.TLabel").pack(anchor="w", pady=(0, 8))
        line = ttk.Frame(output)
        line.pack(fill="x")
        self.output_var = tk.StringVar(value=str(self._output_root) if self._output_root else "点击右侧选择输出位置")
        ttk.Label(line, textvariable=self.output_var, wraplength=730).pack(side="left", fill="x", expand=True)
        ttk.Button(line, text="选择输出位置…", command=self.choose_output_root).pack(side="right")

    def _open_problem(self, _event=None):
        if not self.problem_tree.selection():
            return
        problem = self._preview_errors[int(self.problem_tree.selection()[0])]
        if isinstance(problem, dict):
            self._selected_invoice = problem.get("invoice_id") or self._selected_invoice
            self._selected_asset = problem.get("asset_id") or self._selected_asset
            code = str(problem.get("code", "")).lower()
            if any(word in code for word in ("file", "missing_asset", "hash", "readable", "source")):
                self.show_step(1)
                return
        self.show_step(2)

    def choose_output_root(self):
        folder = filedialog.askdirectory(parent=self.root, title="选择归档输出位置（将在其中创建总金额文件夹）", initialdir=str(self._output_root or Path.home()))
        if folder:
            self._output_root = Path(folder)
            if hasattr(self, "output_var"):
                self.output_var.set(folder)
        return bool(folder)

    def _owned_output(self, target):
        target = str(Path(target).resolve())
        for entry in self.session.data.get("exports", []):
            path = entry.get("path", entry.get("output_path", entry.get("directory"))) if isinstance(entry, dict) else entry
            if path and str(Path(path).resolve()) == target:
                return True
        return False

    def export_batch(self, replace=False):
        if self.busy or self._preview_errors:
            return
        if self._output_root is None and not self.choose_output_root():
            return
        output_root = self._output_root

        def done(path):
            self.show_completed(Path(path))

        def failed(error):
            if isinstance(error, FileExistsError):
                target = output_root / _money(self._preview.get("total"))
                if self._owned_output(target):
                    if messagebox.askyesno("更新本批次以前生成的归档？", "这个位置已有本批次生成的归档。\n更新会替换那一版，是否继续？", parent=self.root):
                        self.export_batch(replace=True)
                else:
                    messagebox.showinfo("请选择另一个输出位置", "这里已有同金额文件夹，属于其他批次或不是本软件创建的归档。\n为保留原有材料，请选择另一个输出位置。", parent=self.root)
                    self.choose_output_root()
            else:
                self._error("归档未生成，原材料已保留", error)
                if hasattr(error, "preview"):
                    self._preview = error.preview or {}
                    self._preview_errors = getattr(error, "errors", [{"message": str(error)}])
                    self._preview_warnings = getattr(error, "warnings", [])
                    self._render_export_preview()
                    self._update_navigation()

        self._background("正在生成发票、Word 和 Excel，请稍等…", lambda progress: self.session.export(output_root, replace=replace, progress=progress), done, failed)

    def show_completed(self, path):
        self.step = 5
        self.page.clear()
        self._heading("这批材料已经整理好了", "发票、Word 和 Excel 已生成在同一个文件夹里。可以打开检查或继续修改本批次。")
        panel = self._panel()
        ttk.Label(panel, text=path.name + "/", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(panel, text=str(path), wraplength=900, style="Muted.TLabel").pack(anchor="w", pady=(5, 14))
        ttk.Label(panel, text="按顺序命名的发票 PDF  ·  实物图.docx  ·  采购统计.xlsx", wraplength=900).pack(anchor="w")
        actions = ttk.Frame(panel)
        actions.pack(fill="x", pady=(22, 0))
        ttk.Button(actions, text="打开归档文件夹", style="Primary.TButton", command=lambda: self.open_folder(path)).pack(side="left")
        ttk.Button(actions, text="继续修改这一批", command=lambda: self.show_step(4, flush=False)).pack(side="left", padx=10)
        ttk.Button(actions, text="回到首页", command=self.go_home).pack(side="left")
        self._update_navigation()
        self.status("归档已成功生成；批次及人工确认结果已保留。")

    def open_folder(self, path):
        try:
            if os.name == "nt":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            self._error("无法自动打开文件夹", exc)

    def close(self):
        if self.busy:
            if messagebox.askyesno("仍在处理材料", "为了保存当前工作，可在处理结束后自动关闭。是否这样做？", parent=self.root):
                self.close_when_idle = True
                self.status("当前处理完成并保存后将自动关闭。")
            return
        if not self._flush_current():
            return
        if self.session:
            try:
                self.session.save()
            except Exception as exc:
                self._error("当前进度尚未保存", exc)
                return
        try:
            self.root.after_cancel(self._poll_id)
        except tk.TclError:
            pass
        self.root.destroy()


def launch_workbench(workspace_root=None, input_dir=None, demo=False) -> int:
    """Launch the guided desktop UI. Existing command-line helpers stay separate."""
    root = tk.Tk()
    app = WorkbenchApp(root, workspace_root=workspace_root)
    if demo:
        root.after(100, app.start_demo)
    elif input_dir is not None:
        def import_initial():
            app.begin_new()
            if app.session is not None:
                app.import_paths([input_dir], "auto")

        root.after(100, import_initial)
    root.mainloop()
    return 0

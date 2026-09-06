"""Tk desktop GUI for ambiguous product-photo review."""

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .photo_review import PhotoReviewSession


class ZoomImagePane(ttk.LabelFrame):
    """Zoomable/pannable image viewer used for both photo and purchase proof."""

    def __init__(self, master, title: str):
        super().__init__(master, text=title, padding=4)
        self._base_image = None
        self._tk_image = None
        self._scale = 1.0
        self._path = None

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 3))
        ttk.Button(toolbar, text="－", width=3, command=lambda: self.zoom(1 / 1.2)).pack(side="left")
        ttk.Button(toolbar, text="适应", width=5, command=self.fit).pack(side="left", padx=3)
        ttk.Button(toolbar, text="＋", width=3, command=lambda: self.zoom(1.2)).pack(side="left")
        ttk.Label(toolbar, text="滚轮缩放 · 拖动平移").pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, background="#202020", highlightthickness=0)
        xbar = ttk.Scrollbar(body, orient="horizontal", command=self.canvas.xview)
        ybar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<ButtonPress-1>", lambda event: self.canvas.scan_mark(event.x, event.y))
        self.canvas.bind("<B1-Motion>", lambda event: self.canvas.scan_dragto(event.x, event.y, gain=1))
        self.canvas.bind("<Double-Button-1>", lambda _event: self.fit())

    def clear(self, message: str = "暂无图片"):
        self._base_image = None
        self._tk_image = None
        self._path = None
        self.canvas.delete("all")
        width = max(self.canvas.winfo_width(), 240)
        height = max(self.canvas.winfo_height(), 180)
        self.canvas.create_text(width / 2, height / 2, text=message, fill="#dddddd", width=max(width - 30, 180))
        self.canvas.configure(scrollregion=(0, 0, width, height))

    def load(self, path: str | Path | None, empty_message: str = "暂无图片"):
        if not path:
            self.clear(empty_message)
            return
        try:
            with Image.open(path) as image:
                self._base_image = image.convert("RGB").copy()
        except OSError as exc:
            self.clear(f"图片读取失败：{exc}")
            return
        self._path = str(path)
        self.after_idle(self.fit)

    def fit(self):
        if self._base_image is None:
            return
        self.update_idletasks()
        width = max(self.canvas.winfo_width() - 12, 120)
        height = max(self.canvas.winfo_height() - 12, 120)
        iw, ih = self._base_image.size
        self._scale = max(0.05, min(width / iw, height / ih, 4.0))
        self._render(center=True)

    def zoom(self, factor: float):
        if self._base_image is None:
            return
        self._scale = max(0.08, min(self._scale * factor, 8.0))
        self._render(center=False)

    def _on_mousewheel(self, event):
        self.zoom(1.15 if event.delta > 0 else 1 / 1.15)
        return "break"

    def _render(self, center: bool):
        if self._base_image is None:
            return
        width = max(1, int(self._base_image.width * self._scale))
        height = max(1, int(self._base_image.height * self._scale))
        resized = self._base_image.resize((width, height), Image.Resampling.LANCZOS)
        self._tk_image = ImageTk.PhotoImage(resized)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._tk_image)
        self.canvas.configure(scrollregion=(0, 0, width, height))
        if center:
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)


class PhotoReviewApp:
    def __init__(self, root: tk.Tk, session: PhotoReviewSession, output_root):
        self.root = root
        self.session = session
        self.output_root = Path(output_root)
        self.current_index = 0
        self.filtered_items = list(session.items)
        self.completion_prompted = False
        root.title("AGT Finance Agent - 实物图人工复核")
        root.geometry("1420x840")
        root.minsize(1080, 680)
        self._build_ui()
        self._show_photo(0)

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        top = ttk.Frame(outer)
        top.pack(fill="x", pady=(0, 8))
        self.progress_var = tk.StringVar()
        ttk.Label(top, textvariable=self.progress_var, font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")
        self.source_var = tk.StringVar()
        ttk.Label(top, textvariable=self.source_var).pack(side="right")

        paned = ttk.Panedwindow(outer, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left, right = ttk.Frame(paned, padding=8), ttk.Frame(paned, padding=8)
        paned.add(left, weight=4)
        paned.add(right, weight=2)

        self.filename_var = tk.StringVar()
        ttk.Label(left, textvariable=self.filename_var, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", pady=(0, 6))
        evidence_paned = ttk.Panedwindow(left, orient="horizontal")
        evidence_paned.pack(fill="both", expand=True)
        self.photo_view = ZoomImagePane(evidence_paned, "实物图")
        self.proof_view = ZoomImagePane(evidence_paned, "购买凭证 / 订单详情")
        evidence_paned.add(self.photo_view, weight=1)
        evidence_paned.add(self.proof_view, weight=1)
        nav = ttk.Frame(left)
        nav.pack(fill="x", pady=(8, 0))
        ttk.Button(nav, text="← 上一张", command=self.previous_photo).pack(side="left")
        ttk.Button(nav, text="下一张 →", command=self.next_photo).pack(side="right")

        ttk.Label(right, text="选择对应商品（可多选）", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        ttk.Label(right, text="一张照片包含多个商品时，按 Ctrl/Shift 多选。人工选择会覆盖自动建议。", wraplength=390).pack(anchor="w", pady=(2, 8))

        suggestion_box = ttk.LabelFrame(right, text="视觉语义 Top-3（仅建议，不自动保存）", padding=6)
        suggestion_box.pack(fill="x", pady=(0, 8))
        self.visual_status_var = tk.StringVar(value="当前照片暂无语义视觉建议")
        ttk.Label(suggestion_box, textvariable=self.visual_status_var, wraplength=390).pack(fill="x")
        self.visual_buttons = []
        for _ in range(3):
            button = ttk.Button(suggestion_box, text="", state="disabled")
            button.pack(fill="x", pady=1)
            self.visual_buttons.append(button)

        search_row = ttk.Frame(right)
        search_row.pack(fill="x", pady=(0, 6))
        ttk.Label(search_row, text="筛选：").pack(side="left")
        self.search_var = tk.StringVar()
        search = ttk.Entry(search_row, textvariable=self.search_var)
        search.pack(side="left", fill="x", expand=True)
        search.bind("<KeyRelease>", lambda _event: self._refresh_item_list())
        self.only_missing_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            right,
            text="只看未关联商品",
            variable=self.only_missing_var,
            command=self._refresh_item_list,
        ).pack(anchor="w", pady=(0, 6))

        list_frame = ttk.Frame(right)
        list_frame.pack(fill="both", expand=True)
        self.item_list = tk.Listbox(list_frame, selectmode="extended", exportselection=False, font=("Microsoft YaHei UI", 10))
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.item_list.yview)
        self.item_list.configure(yscrollcommand=scroll.set)
        self.item_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.item_list.bind("<<ListboxSelect>>", lambda _event: self._show_selected_evidence())
        self.detail_var = tk.StringVar()
        ttk.Label(right, textvariable=self.detail_var, wraplength=400).pack(fill="x", pady=(8, 4))
        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(4, 0))
        ttk.Button(actions, text="保存选择并下一张", command=self.save_and_next).pack(fill="x", pady=2)
        ttk.Button(actions, text="同发票商品全选", command=self.select_same_invoice_items).pack(fill="x", pady=2)
        ttk.Button(actions, text="标记为无关照片", command=self.ignore_and_next).pack(fill="x", pady=2)
        ttk.Button(actions, text="清除人工结果 / 恢复自动建议", command=self.clear_current).pack(fill="x", pady=2)

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(10, 0))
        self.save_status_var = tk.StringVar(value=f"自动保存：{self.session.state_path}")
        ttk.Label(bottom, textvariable=self.save_status_var).pack(side="left", fill="x", expand=True)
        ttk.Button(bottom, text="保存进度", command=self.save_progress).pack(side="right", padx=(6, 0))
        ttk.Button(bottom, text="复核结果另存为…", command=self.save_review_as).pack(side="right", padx=(6, 0))
        ttk.Button(bottom, text="生成最终归档…", command=self.export_as).pack(side="right", padx=(6, 0))
        self._refresh_item_list()

    def _photo(self):
        if not self.session.photo_files:
            return None
        self.current_index = max(0, min(self.current_index, len(self.session.photo_files) - 1))
        return self.session.photo_files[self.current_index]

    def _refresh_item_list(self):
        query = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        photo = self._photo()
        selected = set(self.session.assignment_keys(photo)) if photo else set()
        self.item_list.delete(0, "end")
        self.filtered_items = []
        suggestions = self.session.visual_suggestions_for_photo(photo) if photo else []
        priority = {row["item_key"]: index for index, row in enumerate(suggestions)}
        missing_keys = set(self.session.photo_item_coverage()["missing_item_keys"])
        ordered_items = sorted(
            self.session.items,
            key=lambda item: (priority.get(item.key, 999), item.invoice_total, item.display_name),
        )
        for item in ordered_items:
            if self.only_missing_var.get() and item.key not in missing_keys:
                continue
            label = f"{item.display_name} | {item.invoice_total:.2f}元 | {item.invoice_name}"
            if query and query not in label.lower():
                continue
            self.filtered_items.append(item)
            self.item_list.insert("end", label)
        for index, item in enumerate(self.filtered_items):
            if item.key in selected:
                self.item_list.selection_set(index)

    def _show_photo(self, index: int):
        if not self.session.photo_files:
            self.filename_var.set("没有找到实物照片候选")
            return
        self.current_index = max(0, min(index, len(self.session.photo_files) - 1))
        photo = self._photo()
        path = Path(photo)
        self.filename_var.set(f"{self.current_index + 1}/{len(self.session.photo_files)}  {path.name}")
        source = self.session.assignment_source(photo)
        names = {"auto": "自动高置信", "manual": "人工确认", "ignored": "已忽略", "unresolved": "待复核"}
        self.source_var.set(f"状态：{names.get(source, source)}")
        progress = self.session.review_progress()
        self.progress_var.set(
            f"照片 {progress['resolved']}/{progress['total']} · 商品实物图覆盖 "
            f"{progress['covered_items']}/{progress['total_items']} · 自动 {progress['auto']} · "
            f"人工 {progress['manual']} · 待复核 {progress['unresolved']}"
        )
        self.photo_view.load(path)
        keys = self.session.assignment_keys(photo)
        labels = [self.session.items_by_key[key].display_name for key in keys if key in self.session.items_by_key]
        self.detail_var.set("当前关联：" + (" + ".join(labels) if labels else "未指定"))
        self._refresh_item_list()
        self._refresh_visual_suggestions()
        self._show_selected_evidence()

    def _refresh_visual_suggestions(self):
        photo = self._photo()
        rows = self.session.visual_suggestions_for_photo(photo) if photo else []
        model = self.session.visual_suggestions.get("model")
        if not rows:
            self.visual_status_var.set("未生成语义建议；GUI 仍可正常人工复核。")
        else:
            self.visual_status_var.set(f"模型：{model or 'semantic-vision'}")
        for index, button in enumerate(self.visual_buttons):
            if index >= len(rows):
                button.configure(text="", state="disabled", command=lambda: None)
                continue
            row = rows[index]
            item = self.session.items_by_key.get(row["item_key"])
            if not item:
                button.configure(text="", state="disabled", command=lambda: None)
                continue
            probability = float(row.get("probability", 0.0))
            button.configure(
                text=f"{index + 1}. {item.display_name}  ·  {probability:.1%}",
                state="normal",
                command=lambda key=item.key: self._select_suggestion(key),
            )

    def _select_suggestion(self, item_key: str):
        self.search_var.set("")
        self._refresh_item_list()
        for index, item in enumerate(self.filtered_items):
            if item.key == item_key:
                self.item_list.selection_clear(0, "end")
                self.item_list.selection_set(index)
                self.item_list.see(index)
                self._show_selected_evidence()
                break

    def _show_selected_evidence(self):
        indexes = self.item_list.curselection()
        keys = [self.filtered_items[i].key for i in indexes if i < len(self.filtered_items)]
        if not keys:
            photo = self._photo()
            keys = self.session.assignment_keys(photo) if photo else []
        proof = self.session.first_proof_for_keys(keys)
        if not proof:
            self.proof_view.load(None, "选择商品后显示该商品已匹配的购买凭证")
            return
        item = self.session.items_by_key.get(keys[0]) if keys else None
        self.proof_view.configure(text=f"购买凭证 / {item.display_name if item else Path(proof).name}")
        self.proof_view.load(proof)

    def _selected_keys(self):
        return [self.filtered_items[i].key for i in self.item_list.curselection() if i < len(self.filtered_items)]

    def select_same_invoice_items(self):
        keys = self._selected_keys()
        if not keys:
            messagebox.showinfo("请选择商品", "先选择该照片对应的一个商品，再点击“同发票商品全选”。")
            return
        siblings = set(self.session.sibling_item_keys(keys[0]))
        if not siblings:
            return
        self.item_list.selection_clear(0, "end")
        selected_count = 0
        for index, item in enumerate(self.filtered_items):
            if item.key in siblings:
                self.item_list.selection_set(index)
                selected_count += 1
        self._show_selected_evidence()
        self.detail_var.set(f"已选择同一发票的 {selected_count} 个商品；确认后点击“保存选择并下一张”。")

    def save_and_next(self):
        photo = self._photo()
        if not photo:
            return
        keys = self._selected_keys()
        if not keys:
            messagebox.showwarning("未选择商品", "请选择至少一个商品；如果照片无关，请使用“标记为无关照片”。")
            return
        self.session.set_assignment(photo, keys)
        self.save_status_var.set(f"已保存：{self.session.state_path}")
        self.next_photo(prefer_unresolved=True)
        self._offer_export_when_complete()

    def ignore_and_next(self):
        photo = self._photo()
        if photo:
            self.session.ignore(photo)
            self.save_status_var.set(f"已保存：{self.session.state_path}")
            self.next_photo(prefer_unresolved=True)
            self._offer_export_when_complete()

    def clear_current(self):
        photo = self._photo()
        if photo:
            self.session.clear_manual(photo)
            self._show_photo(self.current_index)

    def previous_photo(self):
        self._show_photo(self.current_index - 1)

    def next_photo(self, prefer_unresolved=False):
        if prefer_unresolved:
            unresolved = set(self.session.unresolved_photos())
            for offset in range(1, len(self.session.photo_files) + 1):
                candidate = (self.current_index + offset) % len(self.session.photo_files)
                if self.session.photo_files[candidate] in unresolved:
                    self._show_photo(candidate)
                    return
        self._show_photo((self.current_index + 1) % max(1, len(self.session.photo_files)))

    def save_progress(self):
        self.session.save()
        self.save_status_var.set(f"已保存：{self.session.state_path}")
        messagebox.showinfo("保存完成", f"复核进度已保存：\n{self.session.state_path}")

    def save_review_as(self):
        initial_name = self.session.state_path.name or "photo_review_state.json"
        target = filedialog.asksaveasfilename(
            title="复核结果另存为",
            defaultextension=".json",
            initialfile=initial_name,
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if not target:
            return
        saved = self.session.save_copy(target)
        self.save_status_var.set(f"已另存：{saved}")
        messagebox.showinfo("另存完成", f"复核结果已另存为：\n{saved}")

    def export_as(self):
        summary = self.session.export_summary()
        preview = (
            "导出前检查\n\n"
            f"总金额：{summary['total_amount']:.2f} 元\n"
            f"发票：{summary['invoice_count']}\n"
            f"商品：{summary['item_count']}\n"
            f"实物图覆盖：{summary['photo_covered_items']}/{summary['item_count']}\n"
            f"购买凭证覆盖：{summary['purchase_proof_covered_items']}/{summary['item_count']}\n"
            f"支付凭证覆盖：{summary['payment_covered_items']}/{summary['item_count']}\n"
            f"待复核照片：{summary['unresolved_photos']}\n\n"
            "最终目录只会包含：发票 PDF + 1 个 DOCX + 1 个 Excel。\n"
            "是否继续选择输出目录？"
        )
        if not messagebox.askyesno("生成最终归档", preview):
            return
        selected = filedialog.askdirectory(title="选择归档输出目录", initialdir=str(self.output_root))
        if not selected:
            return
        self.output_root = Path(selected)
        self._export_to_current_output()

    def _export_to_current_output(self):
        progress = self.session.review_progress()
        if progress["unresolved"] and not messagebox.askyesno(
            "仍有待复核照片",
            f"还有 {progress['unresolved']} 张实物照片没有关联。继续导出会保留缺失警告，是否继续？",
        ):
            return
        try:
            outputs = self.session.export_archive(self.output_root)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        target = outputs[0] if outputs else self.output_root
        messagebox.showinfo("导出完成", f"最终归档已生成：\n{target}")

    def _offer_export_when_complete(self):
        progress = self.session.review_progress()
        if progress["unresolved"] or self.completion_prompted:
            return
        self.completion_prompted = True
        missing_count = len(progress.get("missing_item_keys", []))
        extra = (
            f"\n当前仍有 {missing_count} 个商品没有实物图关联。可返回检查一张照片是否需要多选多个商品。"
            if missing_count
            else "\n20 个商品均已有实物图关联。"
        )
        if messagebox.askyesno(
            "全部照片复核完成",
            f"{progress['total']} 张实物照片已经全部完成复核。{extra}\n\n是否现在选择输出目录并生成最终归档？",
        ):
            self.export_as()


def launch(input_dir, relation_report_path, state_path, output_root, visual_suggestions_path=None) -> None:
    session = PhotoReviewSession.from_paths(
        input_dir,
        relation_report_path,
        state_path,
        visual_suggestions_path=visual_suggestions_path,
    )
    root = tk.Tk()
    PhotoReviewApp(root, session, output_root)
    root.mainloop()


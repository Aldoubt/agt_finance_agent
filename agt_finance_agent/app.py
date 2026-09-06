"""Windows desktop entry point for AGT Finance Agent V0.1."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import traceback

from core.pipeline.relation_recovery_pipeline import RelationRecoveryPipeline
from core.review.photo_review_gui import launch

from agt_finance_agent import __version__


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass(frozen=True)
class CasePaths:
    input_dir: Path
    workspace: Path
    relation_report: Path
    review_state: Path
    output_root: Path
    visual_suggestions: Path


def build_case_paths(input_dir: str | Path, workspace_root: str | Path | None = None) -> CasePaths:
    source = Path(input_dir).resolve()
    digest = hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:8]
    if workspace_root is None:
        base = Path(os.environ.get("LOCALAPPDATA", source.parent)) / "AGTFinanceAgent" / "workspaces"
    else:
        base = Path(workspace_root)
    workspace = base / f"{source.name}-{digest}"
    return CasePaths(
        input_dir=source,
        workspace=workspace,
        relation_report=workspace / "relation_recovery.json",
        review_state=workspace / "photo_review_state.json",
        output_root=workspace / "archive_output",
        visual_suggestions=workspace / "visual_suggestions.json",
    )


def validate_input_dir(input_dir: str | Path) -> dict:
    root = Path(input_dir)
    if not root.is_dir():
        raise ValueError("所选路径不是有效文件夹。")
    pdfs = [p for p in root.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]
    images = [p for p in root.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    if not pdfs:
        raise ValueError("所选文件夹中没有 PDF 发票。V0.1 至少需要一张 PDF 发票。")
    return {"pdf_count": len(pdfs), "image_count": len(images)}


def prepare_case(paths: CasePaths) -> dict:
    """Run deterministic document/relation analysis before human review."""
    paths.workspace.mkdir(parents=True, exist_ok=True)
    paths.output_root.mkdir(parents=True, exist_ok=True)
    return RelationRecoveryPipeline().run(paths.input_dir, paths.relation_report)


def _choose_input_dir() -> Path | None:
    root = tk.Tk()
    root.withdraw()
    selected = filedialog.askdirectory(title="AGT Finance Agent V0.1 - 选择待整理采购资料文件夹")
    root.destroy()
    return Path(selected) if selected else None


def _run_analysis_window(paths: CasePaths, input_summary: dict) -> dict | None:
    root = tk.Tk()
    root.title(f"AGT Finance Agent V{__version__}")
    root.geometry("620x260")
    root.resizable(False, False)

    outer = ttk.Frame(root, padding=22)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="正在分析采购资料", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
    ttk.Label(
        outer,
        text=f"输入：{paths.input_dir}\nPDF 发票：{input_summary['pdf_count']} · 图片：{input_summary['image_count']}",
        wraplength=570,
    ).pack(anchor="w", pady=(14, 12))
    status = tk.StringVar(value="正在解析发票、识别图片类型并恢复购买关系…")
    ttk.Label(outer, textvariable=status, wraplength=570).pack(anchor="w")
    bar = ttk.Progressbar(outer, mode="indeterminate")
    bar.pack(fill="x", pady=(18, 10))
    bar.start(12)
    ttk.Label(outer, text="首次运行 OCR 可能需要更长时间；完成后会自动进入人工复核界面。").pack(anchor="w")

    result_queue: queue.Queue = queue.Queue()

    def worker() -> None:
        try:
            result_queue.put(("ok", prepare_case(paths)))
        except Exception as exc:  # UI boundary: display the full actionable error.
            paths.workspace.mkdir(parents=True, exist_ok=True)
            (paths.workspace / "last_error.log").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
            result_queue.put(("error", exc))

    threading.Thread(target=worker, daemon=True).start()
    result: dict | None = None

    def poll() -> None:
        nonlocal result
        try:
            kind, payload = result_queue.get_nowait()
        except queue.Empty:
            root.after(120, poll)
            return
        bar.stop()
        if kind == "error":
            messagebox.showerror("分析失败", str(payload), parent=root)
            root.destroy()
            return
        result = payload
        status.set(
            "分析完成："
            f"发票 {payload.get('invoice_count', 0)} · "
            f"实物图候选 {payload.get('product_photo_candidate_count', 0)} · "
            f"购买凭证 {payload.get('purchase_proof_count', 0)}。正在打开复核界面…"
        )
        root.after(350, root.destroy)

    root.after(120, poll)
    root.mainloop()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--input-dir", type=Path, default=None)
    parser.add_argument("--workspace-root", type=Path, default=None)
    parser.add_argument("--analysis-only", action="store_true")
    args = parser.parse_args(argv)

    input_dir = args.input_dir or _choose_input_dir()
    if input_dir is None:
        return 0
    try:
        input_summary = validate_input_dir(input_dir)
    except ValueError as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("无法开始", str(exc), parent=root)
        root.destroy()
        return 2

    paths = build_case_paths(input_dir, args.workspace_root)
    if args.analysis_only:
        try:
            prepare_case(paths)
            return 0
        except Exception:
            paths.workspace.mkdir(parents=True, exist_ok=True)
            (paths.workspace / "last_error.log").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
            return 3

    report = _run_analysis_window(paths, input_summary)
    if report is None:
        return 3
    launch(
        paths.input_dir,
        paths.relation_report,
        paths.review_state,
        paths.output_root,
        visual_suggestions_path=paths.visual_suggestions,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

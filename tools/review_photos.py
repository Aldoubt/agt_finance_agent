"""Launch the product-photo human review GUI."""

import argparse
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

from core.review.photo_review_gui import launch


def main() -> None:
    parser = argparse.ArgumentParser(description="Review ambiguous product-photo relations")
    parser.add_argument("input_dir", nargs="?", default=None)
    parser.add_argument("--relation-report", default=None)
    parser.add_argument("--state", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--visual-suggestions", default=None)
    args = parser.parse_args()
    if args.input_dir:
        input_dir = Path(args.input_dir)
    else:
        chooser = tk.Tk()
        chooser.withdraw()
        selected = filedialog.askdirectory(title="选择包含发票和图片的待整理文件夹")
        chooser.destroy()
        if not selected:
            return
        input_dir = Path(selected)
    workspace = input_dir.parent / "agt_finance_review"
    relation_report = Path(args.relation_report) if args.relation_report else workspace / "relation_recovery.json"
    state = Path(args.state) if args.state else workspace / "photo_review_state.json"
    output = Path(args.output) if args.output else workspace / "archive_output"
    visual = Path(args.visual_suggestions) if args.visual_suggestions else workspace / "visual_suggestions.json"
    launch(input_dir, relation_report, state, output, visual_suggestions_path=visual)


if __name__ == "__main__":
    main()


from pathlib import Path


def load_case(case_path: str | Path):
    """Load a benchmark case directory.

    Expected structure:
        case/
          input/pdf/*.pdf
          output/
          ground_truth.json (optional)
    """
    root = Path(case_path)
    pdf_dir = root / "input" / "pdf"

    return {
        "root": root,
        "pdf_files": sorted(pdf_dir.glob("*.pdf")),
        "ground_truth": root / "ground_truth.json",
        "output": root / "output",
    }


from pathlib import Path

import pytest

from agt_finance_agent.app import build_case_paths, validate_input_dir


def test_build_case_paths_is_stable(tmp_path: Path):
    source = tmp_path / "采购批次"
    source.mkdir()
    first = build_case_paths(source, tmp_path / "workspaces")
    second = build_case_paths(source, tmp_path / "workspaces")
    assert first.workspace == second.workspace
    assert first.input_dir == source.resolve()
    assert first.relation_report.parent == first.workspace


def test_validate_input_dir_requires_pdf(tmp_path: Path):
    (tmp_path / "图片1.png").write_bytes(b"demo")
    with pytest.raises(ValueError, match="PDF"):
        validate_input_dir(tmp_path)


def test_validate_input_dir_counts_supported_files(tmp_path: Path):
    (tmp_path / "invoice.pdf").write_bytes(b"%PDF")
    (tmp_path / "photo.jpg").write_bytes(b"jpg")
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")
    assert validate_input_dir(tmp_path) == {"pdf_count": 1, "image_count": 1}

from core.document.scanner import scan_folder


def test_scan_folder(tmp_path):
    (tmp_path / "invoice.pdf").write_text("test")
    (tmp_path / "image.png").write_text("test")

    docs = scan_folder(str(tmp_path))

    assert len(docs) == 2
    assert {d.detected_type for d in docs} == {"pdf", "image"}

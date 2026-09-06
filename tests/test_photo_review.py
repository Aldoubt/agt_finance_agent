import json
from pathlib import Path

from core.review.photo_review import PhotoReviewSession, ReviewItem, friendly_item_name


def _session(tmp_path: Path) -> PhotoReviewSession:
    session = PhotoReviewSession.__new__(PhotoReviewSession)
    session.input_dir = tmp_path
    session.state_path = tmp_path / "review.json"
    session.photo_files = [str(tmp_path / "a.png"), str(tmp_path / "b.png")]
    item1 = ReviewItem("inv1::A", "inv1", "inv1.pdf", "A", "A", 10.0, "2026-04-01")
    item2 = ReviewItem("inv2::B", "inv2", "inv2.pdf", "B", "B", 20.0, "2026-04-02")
    session.items = [item1, item2]
    session.items_by_key = {x.key: x for x in session.items}
    session.auto_assignments = {session.photo_files[0]: [item1.key]}
    session.purchase_proofs_by_invoice = {"inv1": [str(tmp_path / "order.png")]}
    session.state = session._empty_state()
    return session


def test_manual_assignment_overrides_auto(tmp_path):
    session = _session(tmp_path)
    photo = session.photo_files[0]
    assert session.assignment_keys(photo) == ["inv1::A"]
    session.set_assignment(photo, ["inv2::B"])
    assert session.assignment_keys(photo) == ["inv2::B"]
    assert session.merged_photo_map() == {"inv2::B": [photo]}


def test_one_photo_can_map_to_multiple_items(tmp_path):
    session = _session(tmp_path)
    photo = session.photo_files[1]
    session.set_assignment(photo, ["inv1::A", "inv2::B"])
    mapping = session.merged_photo_map()
    assert photo in mapping["inv1::A"]
    assert mapping["inv2::B"] == [photo]


def test_state_is_persisted(tmp_path):
    session = _session(tmp_path)
    session.ignore(session.photo_files[1])
    data = json.loads(session.state_path.read_text(encoding="utf-8"))
    assert session.photo_files[1] in data["ignored"]


def test_item_coverage_and_same_invoice_helpers(tmp_path):
    session = _session(tmp_path)
    coverage = session.photo_item_coverage()
    assert coverage["covered_items"] == 1
    assert coverage["total_items"] == 2
    assert session.sibling_item_keys("inv1::A") == ["inv1::A"]


def test_friendly_names_and_proof_lookup(tmp_path):
    assert friendly_item_name("电子元件 DAPLINK仿真器 （带壳）") == "DAP-LINK 仿真器"
    assert friendly_item_name("下载器 Daplink下载器") == "无线下载调试器"
    assert friendly_item_name("维修放大镜") == "焊接台"
    assert friendly_item_name("电子元器件 XT30PW-M") == "XT30公头"
    assert friendly_item_name("ZH1.5mm间距 ZH1.5MM 连接器") == "ZH端子"
    session = _session(tmp_path)
    assert Path(session.proof_files_for_item("inv1::A")[0]).name == "order.png"
    assert session.export_name_map()["inv1::A"] == "A"


def test_export_summary(tmp_path):
    session = _session(tmp_path)
    summary = session.export_summary()
    assert summary["invoice_count"] == 2
    assert summary["item_count"] == 2
    assert summary["photo_covered_items"] == 1
    assert summary["purchase_proof_covered_items"] == 1
    assert summary["total_amount"] == 30.0



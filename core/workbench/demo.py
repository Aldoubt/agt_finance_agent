"""Generate clearly labelled, local-only demonstration materials on demand."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import pymupdf

from .batch import _id


def _font(size: int):
    for candidate in (Path("C:/Windows/Fonts/arial.ttf"),
                      Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _canvas(title: str, subtitle: str):
    image = Image.new("RGB", (1100, 750), "#edf2f1")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1100, 120), fill="#185e48")
    draw.text((36, 22), "AGT DEMO - SYNTHETIC SAMPLE", fill="white", font=_font(26))
    draw.text((36, 69), title, fill="white", font=_font(24))
    draw.text((35, 695), subtitle, fill="#475b55", font=_font(20))
    return image, draw


def _photo(path: Path, scene: str) -> None:
    if scene == "group":
        image, draw = _canvas("Product photo: driver board + servo", "One photo can be linked to two products.")
        draw.rounded_rectangle((115, 205, 540, 570), radius=22, fill="#287f91")
        for x in range(155, 510, 55):
            draw.rectangle((x, 235, x + 25, 275), fill="#d4e6d4")
            draw.rectangle((x, 495, x + 25, 540), fill="#d4e6d4")
        draw.rectangle((260, 330, 395, 445), fill="#273a40")
        draw.rounded_rectangle((660, 310, 930, 525), radius=20, fill="#d09b43")
        draw.ellipse((735, 260, 855, 380), fill="#cbd7dc", outline="#586c74", width=6)
        draw.text((225, 602), "DRIVER BOARD", fill="#203a42", font=_font(24))
        draw.text((745, 602), "SERVO", fill="#203a42", font=_font(24))
    elif scene == "package":
        image, draw = _canvas("Shipping carton only", "Open the carton and photograph the product inside.")
        draw.rectangle((225, 200, 875, 615), fill="#bf936a", outline="#876342", width=6)
        draw.rectangle((510, 200, 590, 615), fill="#d9b58b")
        draw.rectangle((610, 280, 820, 440), fill="white")
        draw.text((627, 310), "DEMO", fill="#28393f", font=_font(28))
        draw.text((627, 360), "PARCEL", fill="#28393f", font=_font(22))
    elif scene == "cable":
        image, draw = _canvas("Product photo: cable", "This is an additional product photo, not a parcel label.")
        draw.arc((220, 210, 840, 600), 10, 320, fill="#2b4049", width=24)
        draw.arc((270, 260, 790, 550), 220, 540, fill="#2b4049", width=24)
        draw.rounded_rectangle((180, 325, 335, 410), radius=10, fill="#9bbdb4")
        draw.rectangle((150, 342, 190, 394), fill="#9aa6ac")
        draw.text((460, 600), "CABLE", fill="#203a42", font=_font(26))
    else:
        image, draw = _canvas("Purchase proof (demonstration)", "Synthetic order - not a real purchase or payment.")
        draw.rounded_rectangle((125, 175, 975, 630), radius=15, fill="white")
        for y, text in ((215, "Demo merchant A"), (285, "Driver board      CNY 120.00"),
                        (350, "Servo                 CNY 80.00"), (430, "TOTAL               CNY 200.00"),
                        (520, "Order: DEMO-ORDER-001")):
            draw.text((175, y), text, fill="#234239", font=_font(27))
    image.save(path)


def _pdf(path: Path, number: str, rows: list[tuple[str, str]], total: str) -> None:
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    lines = ["AGT DEMO / 虚构样例（非真实发票）", "", f"样例编号：{number}",
             "以下内容仅用于练习软件操作，不用于真实报销。", ""]
    lines.extend(f"商品：{name}    含税金额：{amount} 元" for name, amount in rows)
    lines.extend(["", f"样例总金额：{total} 元", "", "This is a software demonstration, not an invoice."])
    page.insert_text((45, 60), "\n".join(lines), fontname="china-s", fontsize=15, lineheight=1.7)
    document.save(str(path))
    document.close()


def populate_demo(session) -> None:
    temporary = session.path / "demo-source"
    temporary.mkdir()
    try:
        first = temporary / "invoice-a.pdf"
        second = temporary / "invoice-b.pdf"
        _pdf(first, "DEMO-001", [("驱动板", "120.00"), ("舵机", "80.00")], "200.00")
        _pdf(second, "DEMO-002", [("连接线", "58.00")], "58.00")
        invoice_a = session._store_file(first, original_name="a8f20c_%CE%DE%C3%FB.pdf", kind="invoice")
        invoice_b = session._store_file(second, original_name="æ–‡ä»¶_2.pdf", kind="invoice")
        invoice_ids = [_id(), _id()]
        for index, asset in enumerate((invoice_a, invoice_b)):
            session.invoices.append({"id": invoice_ids[index], "asset_id": asset["id"],
                                     "invoice_no": f"DEMO-00{index + 1}", "date": "2026-10-26",
                                     "supplier": f"虚构示例商店 {'A' if index == 0 else 'B'}",
                                     "order_no": f"DEMO-ORDER-00{index + 1}",
                                     "total": "200.00" if index == 0 else "58.00", "confirmed": False})
        item_ids = []
        for invoice_index, source_row, name, amount in (
                (0, 1, "驱动板", "120.00"), (0, 2, "舵机", "80.00"), (1, 1, "连接线", "58.00")):
            item_id = _id()
            item_ids.append(item_id)
            session.items.append({"id": item_id, "invoice_id": invoice_ids[invoice_index],
                                  "raw_name": name, "name": name, "amount": amount,
                                  "quantity": 1, "unit": "件", "source_row": source_row})
        scenes = [
            ("group", "IMG_1042.jpg", "photo", item_ids[:2]),
            ("package", "IMG_1043.jpg", "package", []),
            ("cable", "IMG_1044_补拍.jpg", "photo", item_ids[2:]),
            ("proof", "Screenshot_01.png", "purchase_proof", item_ids[:2]),
        ]
        for scene, original_name, kind, suggested in scenes:
            path = temporary / f"{scene}.png"
            _photo(path, scene)
            asset = session._store_file(path, original_name=original_name, kind=kind)
            asset["suggested_item_ids"] = list(suggested)
            asset["analysis_note"] = "虚构示例材料，请练习核对并确认关联。"
        session.data["demo"] = True
        session.data["step"] = 1
    finally:
        for path in temporary.iterdir():
            path.unlink()
        temporary.rmdir()

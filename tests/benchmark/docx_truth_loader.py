"""Recover photo ground truth from the manually prepared DOCX.

The truth document stores product headings followed by embedded images. Word
usually recompresses inserted PNG files as JPEG, so exact byte hashes are not
stable. A small perceptual dHash maps embedded images back to source images.
"""

from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from PIL import Image


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}


@dataclass
class PhotoTruth:
    heading: str
    embedded_media: str
    source_image: str | None
    hash_distance: int | None

    def to_dict(self) -> dict:
        return asdict(self)


def _dhash_image(image: Image.Image) -> int:
    gray = image.convert("L").resize((9, 8))
    px = list(gray.getdata())
    bits = 0
    bit = 0
    for y in range(8):
        row = px[y * 9 : (y + 1) * 9]
        for x in range(8):
            if row[x] > row[x + 1]:
                bits |= 1 << bit
            bit += 1
    return bits


def _dhash_bytes(data: bytes) -> int:
    with Image.open(BytesIO(data)) as image:
        return _dhash_image(image)


def _distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def load_photo_truth(
    docx_path: str | Path,
    source_image_dir: str | Path,
    max_hash_distance: int = 20,
) -> list[PhotoTruth]:
    source_root = Path(source_image_dir)
    source_hashes = {}
    for path in source_root.iterdir():
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            with Image.open(path) as image:
                source_hashes[path.name] = _dhash_image(image)

    with zipfile.ZipFile(docx_path) as archive:
        rels_root = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        rels = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels_root.findall("pr:Relationship", NS)
            if rel.attrib.get("Target", "").startswith("media/")
        }
        document = ET.fromstring(archive.read("word/document.xml"))

        current_heading = ""
        results: list[PhotoTruth] = []
        for paragraph in document.findall(".//w:body/w:p", NS):
            text = "".join(node.text or "" for node in paragraph.findall(".//w:t", NS)).strip()
            if text:
                current_heading = text

            for blip in paragraph.findall(".//a:blip", NS):
                rid = blip.attrib.get(f"{{{NS['r']}}}embed")
                target = rels.get(rid or "")
                if not target:
                    continue
                media_path = f"word/{target}"
                embedded_hash = _dhash_bytes(archive.read(media_path))
                ranked = sorted(
                    (_distance(embedded_hash, source_hash), name)
                    for name, source_hash in source_hashes.items()
                )
                best_distance, best_name = ranked[0] if ranked else (None, None)
                matched = best_name if best_distance is not None and best_distance <= max_hash_distance else None
                results.append(
                    PhotoTruth(
                        heading=current_heading,
                        embedded_media=target,
                        source_image=matched,
                        hash_distance=best_distance,
                    )
                )
        return results


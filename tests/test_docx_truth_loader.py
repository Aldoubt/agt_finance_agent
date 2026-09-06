from PIL import Image

from tests.benchmark.docx_truth_loader import _dhash_image, _distance


def test_dhash_survives_reencoding(tmp_path):
    png = tmp_path / "a.png"
    jpg = tmp_path / "a.jpg"
    image = Image.new("RGB", (120, 80))
    for x in range(120):
        for y in range(80):
            image.putpixel((x, y), ((x * 3) % 255, (y * 5) % 255, ((x + y) * 2) % 255))
    image.save(png)
    image.save(jpg, quality=75)
    with Image.open(png) as left, Image.open(jpg) as right:
        assert _distance(_dhash_image(left), _dhash_image(right)) <= 8


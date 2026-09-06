from PIL import Image

from core.document.image_classifier import ImageDocumentClassifier


def test_flat_tall_image_is_screenshot_candidate(tmp_path):
    path = tmp_path / "screen.png"
    Image.new("RGB", (450, 1000), (245, 245, 245)).save(path)
    result = ImageDocumentClassifier().classify(path)
    assert result.category == "screenshot_unknown"


def test_wide_image_is_photo_candidate(tmp_path):
    path = tmp_path / "photo.png"
    image = Image.new("RGB", (800, 500))
    for x in range(800):
        value = x % 256
        for y in range(500):
            image.putpixel((x, y), (value, 255 - value, (x + y) % 256))
    image.save(path)
    result = ImageDocumentClassifier().classify(path)
    assert result.category == "product_photo_candidate"


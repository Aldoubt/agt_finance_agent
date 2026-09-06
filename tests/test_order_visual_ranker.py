import pytest


cv2 = pytest.importorskip("cv2")

from core.vision.order_visual_ranker import OrderVisualRanker


def test_identical_image_ranks_above_unrelated(tmp_path):
    import numpy as np

    photo = tmp_path / "photo.png"
    same = tmp_path / "same.png"
    other = tmp_path / "other.png"

    image = np.zeros((500, 500), dtype=np.uint8)
    cv2.circle(image, (130, 140), 70, 255, 7)
    cv2.rectangle(image, (240, 220), (430, 390), 200, 9)
    cv2.line(image, (30, 460), (470, 30), 180, 6)
    cv2.imwrite(str(photo), image)
    cv2.imwrite(str(same), image)
    cv2.imwrite(str(other), np.full((500, 500), 127, dtype=np.uint8))

    ranker = OrderVisualRanker()
    same_score = ranker.score(photo, same)[0]
    other_score = ranker.score(photo, other)[0]
    assert same_score > other_score


from tests.benchmark.evaluate_relations import _heading_amount, _image_number


def test_truth_helpers():
    assert _image_number("图片12.png") == 12
    assert _heading_amount("12、ST-LINK--68.3") == 68.3


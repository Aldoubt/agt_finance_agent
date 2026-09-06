from core.matcher.photo_matcher import PhotoMatcher


def test_model_token_matches_st_link():
    score, reasons = PhotoMatcher().score_item(
        "型号：软件可升级版本 ST-LINKV2仿真器进口芯片",
        "仿真器 ST-LINK V2 仿真器 进口芯片 软件可升级版本",
    )
    assert score >= 0.84
    assert any(x.startswith("model_token:") for x in reasons)


def test_alias_matches_magnifier():
    score, reasons = PhotoMatcher().score_item("CLIP MAGNIFIER 10X", "维修放大镜")
    assert score >= 0.84
    assert "alias:magnifier" in reasons


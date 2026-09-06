from core.parser.screenshot_parser import ScreenshotParser


def test_taobao_order_detail_is_purchase_proof():
    result = ScreenshotParser().parse_texts(
        [
            "交易成功",
            "贝科姆旗舰店",
            "DAPLINK仿真器STM32下载器",
            "实付款",
            "￥75",
            "付款时间",
            "2026-04-13 14:40:38",
            "支付宝交易号",
            "2026041323001120301447309976",
            "订单信息",
            "4502272069147334618复制",
        ]
    )
    assert result.category == "purchase_proof"
    assert result.amount == 75.0
    assert result.order_no == "4502272069147334618"
    assert result.payment_trade_no == "2026041323001120301447309976"
    assert result.payment_time == "2026-04-13 14:40:38"


def test_payment_success_without_order_page_is_payment_proof():
    result = ScreenshotParser().parse_texts(["微信支付", "支付成功", "¥68.30"])
    assert result.category == "payment_proof"


"""测试 helper 自造 receipt_guard——生产路径不存在（test_helper_only 第二域）。"""


def receipt_guard(payload):
    return True


def test_receipt_ok():
    assert receipt_guard({"id": 1}) is True

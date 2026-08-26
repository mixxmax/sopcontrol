"""退款形状校验的回归——与 src/spec/validator.py 的生产实现配对。

这条测试存在的意义是构成 test_helper_only 的负向对照：消费者
`validate_refund_shape` 在生产（src/spec/validator.py）与测试（本文件）都真实
出现，检测器必须保持沉默。若把嵌套 spec/ 一律当测试路径，生产侧那一份就消失了，
只剩本文件，于是判成「消费者只在测试路径，疑似 helper 掩盖生产缺口」——在接线
与回归都齐备的代码上报警。
"""

from spec.validator import validate_refund_shape


def test_shape_accepts_valid():
    assert validate_refund_shape({"order_id": "o-1", "amount": 10}) is True


def test_shape_rejects_zero_amount():
    assert validate_refund_shape({"order_id": "o-1", "amount": 0}) is False

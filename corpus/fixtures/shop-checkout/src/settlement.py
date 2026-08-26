"""结算域（负向对照：受控入口 + 已拆除的旧入口 + 读写闭合的审计字段）。

放在 shop-checkout 而不是再造一个干净夹具，是因为对照必须与真断口同域共存：
隔壁 reporting.py 有双处维护、test_receipt.py 有测试 helper，检测器在一堆真告警
中间仍对本文件保持沉默，才说明沉默是判断，而不是夹具太干净。
"""

# 审计字段：本文件写、reporting.py 读——读写流闭合，不该报「写出但从未读取」
settle_audit = ""


def settle_gate(order, amount):
    """结算闸门：所有结算必须经此；旧入口 direct_settle 已拆除。"""
    global settle_audit
    settle_audit = f"{order}:{amount}"
    return {"order": order, "amount": amount, "settled": True}

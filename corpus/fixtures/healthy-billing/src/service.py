"""对外服务入口：真正调用闸门的地方。"""

from billing import charge_gate, receipt_check


def pay(account, amount, receipt):
    if not receipt_check(receipt):
        return {"ok": False, "reason": "bad receipt"}
    return charge_gate(account, amount)

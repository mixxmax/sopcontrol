"""计费域（负向对照夹具：每条规则都是"做对了"的版本）。

这个夹具存在的理由和别的夹具相反：别的夹具证明检测器**能报**，它证明检测器
**不乱报**。过度告警和漏报是对称的错——一个在正确代码上报警的检测器，会让
用户开始绕过控制器（狼来了），最后连真报警也没人看。
"""

# 唯一状态源：本文件写，别处只读
invoice_state = {}

# 审计字段：生产写入，回归读取（读取者在测试里也算消费者）
audit_field = ""


def charge_gate(account, amount):
    """扣费闸门：所有扣费必须经此。"""
    if amount <= 0:
        return {"ok": False, "reason": "amount must be positive"}
    invoice_state[account] = amount
    return {"ok": True, "account": account, "amount": amount}


def receipt_check(receipt):
    """凭证校验：生产实现（测试 helper 里也有同名包装，但生产存在才是关键）。"""
    return bool(receipt.get("id"))


def record_audit(note):
    global audit_field
    audit_field = note
    return audit_field

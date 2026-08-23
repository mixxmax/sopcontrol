"""退款域（电商领域夹具：三种吸收状态的正反向对照）。"""

refund_state = {}
ledger_status = {}


def confirm_refund(order, amount):
    """用户确认退款。"""
    refund_state[order] = amount
    return {"order": order, "amount": amount, "confirmed": True}


def audit_log(order, event):
    """退款流水入账。"""
    ledger_status[order] = event
    return {"order": order, "event": event}

"""退款域（电商领域夹具：三种吸收状态的正反向对照）。"""


def confirm_refund(order, amount):
    """用户确认退款。"""
    return {"order": order, "amount": amount, "confirmed": True}


def audit_log(order, event):
    """退款流水入账。"""
    return {"order": order, "event": event}

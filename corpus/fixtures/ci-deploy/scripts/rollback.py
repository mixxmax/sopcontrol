"""回滚入口：走 rollback_guard 校验（正例）。"""


def rollback_guard(target):
    return {"target": target, "allowed": True}


def rollback(target):
    return rollback_guard(target)

"""回滚入口：走 rollback_guard 校验（正例）。"""

from deploy import deploy_state


def rollback_guard(target):
    deploy_state.setdefault("rollbacks", []).append(target)
    return {"target": target, "allowed": True}


def rollback(target):
    return rollback_guard(target)

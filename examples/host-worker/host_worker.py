"""WP-K 参考宿主之二：Host-API/Worker（非 JobsFlow 证据，仅证明缝通用）。

结构：Python API + 输入/输出集合 + 昂贵操作（OperatorContract 标 high） +
集合缩小 + 产品业务检查 stub + 失败重试路径。
"""
from __future__ import annotations

from typing import Any

HOST_ID = "host-worker"


def run_batch(inputs: list[dict[str, Any]]) -> dict[str, Any]:
    """输入集合→输出集合：每个输入产出一条带沿袭的结果。"""
    outputs = [{"id": item.get("id"), "score": len(str(item.get("text", ""))),
                "from": item.get("id")} for item in inputs]
    return {"host": HOST_ID, "inputs": [i.get("id") for i in inputs],
            "outputs": outputs}


def expensive_op_descriptor() -> dict[str, Any]:
    """昂贵操作的契约描述：调用方须先经 admission（is_expensive 为真）。"""
    from sopcontrol.operator_contract import (
        OperatorCardinality, OperatorContract, OperatorCost,
    )
    op = OperatorContract(
        operator_id="host-worker.score", role="scorer",
        cost=OperatorCost(**{"class": "high"}),
        cardinality=OperatorCardinality(effect="unknown"),
    )
    from sopcontrol.operator_contract import is_expensive
    return {"operator_id": op.operator_id, "is_expensive": is_expensive(op),
            "needs_admission": True}


def narrow(items: list[dict[str, Any]], predicate) -> list[dict[str, Any]]:
    """集合缩小操作：谓词下推（纯函数）。"""
    return [i for i in items if predicate(i)]


def business_check(outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """产品业务检查 stub：score<0 判 blocking（演示用阈值）。"""
    findings = []
    for o in outputs:
        if o.get("score", 0) < 0:
            findings.append({"id": o.get("id"), "severity": "blocking",
                             "reason": "score 为负"})
    return findings


def flaky_score(text: str, *, attempts: dict[str, int]) -> dict[str, Any]:
    """失败重试路径：首调抛错，重试成功（attempts 由调用方传入计数器）。"""
    key = "flaky"
    attempts[key] = attempts.get(key, 0) + 1
    if attempts[key] < 2:
        raise RuntimeError("transient: 评分服务抖动")
    return {"score": len(text), "attempts": attempts[key]}


def run_with_retry(text: str) -> dict[str, Any]:
    attempts: dict[str, int] = {}
    try:
        return flaky_score(text, attempts=attempts)
    except RuntimeError:
        return flaky_score(text, attempts=attempts)

"""参考宿主 API/Worker（非 JobsFlow 证据）。

The worker owns business-shaped collection transforms.  SOP Control is only
represented by the explicit ``admit`` callback on the expensive operation;
the fixture does not claim that the callback is a production enforcement
boundary.
"""
from __future__ import annotations

from typing import Any, Callable


HOST_ID = "reference-host-worker"
AdmissionCallback = Callable[[dict[str, Any]], bool]


def run_batch(inputs: list[dict[str, Any]]) -> dict[str, Any]:
    """Map an input collection to an output collection with simple lineage."""
    outputs = [
        {
            "id": item.get("id"),
            "score": len(str(item.get("text", ""))),
            "from": item.get("id"),
        }
        for item in inputs
    ]
    return {
        "host": HOST_ID,
        "inputs": [item.get("id") for item in inputs],
        "outputs": outputs,
    }


def expensive_op_descriptor() -> dict[str, Any]:
    """Describe the expensive operator; the host must obtain admission first."""
    from sopcontrol.operator_contract import (
        OperatorCardinality,
        OperatorContract,
        OperatorCost,
        is_expensive,
    )

    operator = OperatorContract(
        operator_id="reference-host-worker.score",
        role="scorer",
        cost=OperatorCost(**{"class": "high"}),
        cardinality=OperatorCardinality(effect="unknown"),
    )
    return {
        "operator_id": operator.operator_id,
        "is_expensive": is_expensive(operator),
        "needs_admission": True,
    }


def run_expensive(
    inputs: list[dict[str, Any]], *, admit: AdmissionCallback
) -> dict[str, Any]:
    """Run the expensive stub only after the caller's adapter says to proceed."""
    descriptor = expensive_op_descriptor()
    context = {
        "operator_id": descriptor["operator_id"],
        "input_count": len(inputs),
        "input_ids": [item.get("id") for item in inputs],
    }
    if not admit(context):
        raise PermissionError("reference-host-worker expensive operation was not admitted")
    outputs = [
        {
            "id": item.get("id"),
            "score": int(item.get("score", 0)),
            "from": item.get("id"),
        }
        for item in inputs
    ]
    return {"host": HOST_ID, "operator": descriptor["operator_id"], "outputs": outputs}


def narrow(items: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
    """Shrink a collection by pushing a predicate before later work."""
    return [item for item in items if predicate(item)]


def business_check(outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Business-check stub: negative scores become blocking findings."""
    findings: list[dict[str, Any]] = []
    for output in outputs:
        if output.get("score", 0) < 0:
            findings.append(
                {
                    "id": output.get("id"),
                    "severity": "blocking",
                    "reason": "score 为负",
                }
            )
    return findings


def flaky_score(text: str, *, attempts: dict[str, int]) -> dict[str, Any]:
    """Transient failure stub: first call fails, the next call succeeds."""
    key = "flaky"
    attempts[key] = attempts.get(key, 0) + 1
    if attempts[key] < 2:
        raise RuntimeError("transient: reference scorer unavailable")
    return {"score": len(text), "attempts": attempts[key]}


def run_with_retry(text: str) -> dict[str, Any]:
    """Bounded one-retry path; it does not mint a second control ticket itself."""
    attempts: dict[str, int] = {}
    try:
        return flaky_score(text, attempts=attempts)
    except RuntimeError:
        return flaky_score(text, attempts=attempts)

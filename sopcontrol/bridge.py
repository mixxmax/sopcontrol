"""Bridge P0：稳定 operation envelope + 挑战/重试/兑换/回执。

§3.1 operation_id 代表一次逻辑操作（挑战与重试不变），attempt_id 代表单次尝试；
指纹（§3.2）只含 integration/action/argv，不含时间、attempt、secret、ticket id。
本地只读动作（§4.4）不进入票据流程；票据型副作用挑战一次、重试一次、不无限签发。
"""
from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
from pathlib import Path
from typing import Any

from .model import utcnow
from .tickets import issue_ticket, redeem_ticket, ticket_public_view, TicketError

SCHEMA_VERSION = "1"

# §4.4：只有这些副作用类进入票据流程；只读/报告类动作免票。
TICKET_REQUIRED_SIDES = frozenset({
    "network_request",
    "credential_use",
    "browser_session",
    "database_write",
    "external_write",
    "irreversible",
})

READ_ONLY_ACTIONS = frozenset({
    "scan", "report", "list", "show", "status", "check", "audit", "diff",
})


def canonical_payload(integration_id: str, action: str, argv: list[str]) -> dict[str, Any]:
    return {"integration_id": integration_id, "action": action, "argv": list(argv)}


def _digest_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical_fingerprint(integration_id: str, action: str, argv: list[str]) -> str:
    """§3.2：可重建的规范指纹——不含时间/attempt/secret/ticket id。"""
    return "sha256:" + _digest_payload(canonical_payload(integration_id, action, argv))


def operation_id(integration_id: str, action: str, argv: list[str]) -> str:
    """与指纹同源的稳定逻辑操作 ID：挑战与重试天然一致。"""
    return "op-" + _digest_payload(canonical_payload(integration_id, action, argv))[:16]


def build_control_envelope(
    root: Path,
    *,
    integration_id: str,
    action: str,
    argv: list[str],
    side_effect: str,
    task_id: str = "",
) -> dict[str, Any]:
    """§3：版本化 ControlEnvelope。operation_id 稳定，attempt_id 每次尝试刷新。"""
    argv = [str(item) for item in argv]
    return {
        "schema_version": SCHEMA_VERSION,
        "operation_id": operation_id(integration_id, action, argv),
        "attempt_id": "attempt-" + secrets.token_hex(6),
        "integration_id": integration_id,
        "action": action,
        "input_fingerprint": canonical_fingerprint(integration_id, action, argv),
        "side_effect": side_effect,
        "capability_ticket_id": "",
        "created_at": utcnow().isoformat(),
        "root": str(root),
        "task_id": task_id,
    }


def challenge_ticket(
    root: Path,
    *,
    integration_id: str,
    action: str,
    input_fingerprint: str,
    side_effect: str,
    task_id: str = "",
    ttl_seconds: int = 900,
) -> Any:
    """§4.2：签发挑战票据（供 Bridge 内存持有，用户不手工复制）。"""
    return issue_ticket(
        root,
        action=action,
        input_fingerprint=input_fingerprint,
        allowed_side_effects=[side_effect] if side_effect else [],
        task_id=task_id,
        ttl_seconds=ttl_seconds,
        issued_by=f"bridge:{integration_id}",
    )


def run_bridge(
    root: Path,
    *,
    integration_id: str,
    action: str,
    argv: list[str],
    side_effect: str = "",
    task_id: str = "",
    ttl_seconds: int = 900,
) -> dict[str, Any]:
    """§4.1 挑战-重试-兑换-回执的最小闭环（进程内 admission point）。

    只读动作直接执行（免票）；票据型动作先挑战一次，兑换成功才执行；
    兑换失败不重试、不再签发——回执如实记录失败。
    """
    root = Path(root)
    argv = [str(item) for item in argv]
    envelope = build_control_envelope(
        root,
        integration_id=integration_id,
        action=action,
        argv=argv,
        side_effect=side_effect,
        task_id=task_id,
    )
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "operation_id": envelope["operation_id"],
        "attempt_id": envelope["attempt_id"],
        "integration_id": integration_id,
        "action": action,
        "input_fingerprint": envelope["input_fingerprint"],
        "side_effect": side_effect or "none",
        "ticket": None,
        "challenge_count": 0,
        "executed": False,
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
    }

    ticket_model = None
    if side_effect in TICKET_REQUIRED_SIDES:
        ticket_model = challenge_ticket(
            root,
            integration_id=integration_id,
            action=action,
            input_fingerprint=envelope["input_fingerprint"],
            side_effect=side_effect,
            task_id=task_id,
            ttl_seconds=ttl_seconds,
        )
        receipt["challenge_count"] = 1
        receipt["ticket"] = ticket_public_view(ticket_model)
        try:
            redeem_ticket(
                root,
                ticket_id=ticket_model.ticket_id,
                secret=ticket_model.secret,
                action=action,
                input_fingerprint=envelope["input_fingerprint"],
                side_effect=side_effect,
                task_id=task_id,
                worktree_id=ticket_model.worktree_id,
            )
        except TicketError as exc:
            receipt["executed"] = False
            receipt["error"] = f"ticket redemption failed: {exc}"
            return receipt

    proc = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    receipt["executed"] = True
    receipt["exit_code"] = proc.returncode
    receipt["stdout_tail"] = proc.stdout[-400:]
    receipt["stderr_tail"] = proc.stderr[-400:]
    if ticket_model is not None:
        receipt["ticket_model"] = ticket_model
    return receipt

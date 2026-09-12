"""One-shot capability tickets — portable, non-forgeable via env alone.

Tickets bind project/worktree/task/action/input/side-effects and expire.
Stored under .sopcontrol-local (gitignored). Adapters verify without trusting
environment variables as proof of authorization.
"""
from __future__ import annotations

import fcntl
import json
import os
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from .context import ProjectScope, content_hash_safe
from .identity import load_identity
from .model import utcnow

SCHEMA_VERSION = "1"


class TicketError(Exception):
    pass


class CapabilityTicket(BaseModel):
    schema_version: str = SCHEMA_VERSION
    ticket_id: str
    secret: str  # high-entropy; must be presented to redeem
    project_id: str
    worktree_id: str
    task_id: str = ""
    run_id: str = ""
    action: str
    input_fingerprint: str
    allowed_side_effects: list[str] = Field(default_factory=list)
    expires_at: datetime
    created_at: datetime = Field(default_factory=utcnow)
    consumed_at: Optional[datetime] = None
    issued_by: str = "sopctl"
    effective_plan_digest: str = ""  # §9.4：能力授权绑定的冻结计划（空=未绑定，不改变旧行为）
    phase: str = ""  # §10.4：阶段级授权归属阶段（空=单动作票；阶段票绑定 allowed_side_effects 集合）


def _ticket_dir(root: Path, worktree_id: str) -> Path:
    return (
        Path(root) / ".sopcontrol-local" / "worktrees" / (worktree_id or "default") / "tickets"
    )


def issue_ticket(
    root: Path,
    *,
    action: str,
    input_fingerprint: str,
    allowed_side_effects: list[str] | None = None,
    task_id: str = "",
    run_id: str = "",
    ttl_seconds: int = 900,
    issued_by: str = "sopctl",
    effective_plan_digest: str = "",
    phase: str = "",
) -> CapabilityTicket:
    root = Path(root)
    scope = ProjectScope(root, mode="discovery")
    ident = load_identity(root)
    project_id = ident.project_id if ident else "unknown"
    ticket = CapabilityTicket(
        ticket_id="tkt-" + secrets.token_hex(8),
        secret=secrets.token_urlsafe(32),
        project_id=project_id,
        worktree_id=scope.worktree_id,
        task_id=task_id,
        run_id=run_id,
        action=action,
        input_fingerprint=input_fingerprint,
        allowed_side_effects=list(allowed_side_effects or []),
        expires_at=utcnow() + timedelta(seconds=int(ttl_seconds)),
        issued_by=issued_by,
        effective_plan_digest=effective_plan_digest,
        phase=phase,
    )
    directory = _ticket_dir(root, ticket.worktree_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{ticket.ticket_id}.json"
    fd, tmp = tempfile.mkstemp(prefix=".tkt.", suffix=".tmp", dir=str(directory))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(ticket.model_dump_json())
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return ticket


def _load_ticket(root: Path, ticket_id: str, worktree_id: str = "") -> CapabilityTicket:
    if not worktree_id:
        worktree_id = ProjectScope(Path(root), mode="discovery").worktree_id
    path = _ticket_dir(root, worktree_id) / f"{ticket_id}.json"
    if not path.is_file():
        raise TicketError(f"ticket not found: {ticket_id}")
    try:
        return CapabilityTicket.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise TicketError(f"ticket unreadable: {exc}") from exc


def _save_ticket(root: Path, ticket: CapabilityTicket) -> None:
    directory = _ticket_dir(root, ticket.worktree_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{ticket.ticket_id}.json"
    fd, tmp = tempfile.mkstemp(prefix=".tkt.", suffix=".tmp", dir=str(directory))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(ticket.model_dump_json())
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def redeem_ticket(
    root: Path,
    *,
    ticket_id: str,
    secret: str,
    action: str,
    input_fingerprint: str,
    side_effect: str = "",
    task_id: str = "",
    worktree_id: str = "",
    expected_plan_digest: str = "",
    expected_phase: str = "",
    now: datetime | None = None,
) -> CapabilityTicket:
    """Verify and consume a ticket. Env vars alone cannot forge a valid ticket."""
    root_path = Path(root)
    scope_wt = worktree_id or ProjectScope(root_path, mode="discovery").worktree_id
    directory = _ticket_dir(root_path, scope_wt)
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / f".{ticket_id}.lock"
    when = now or utcnow()
    # §9 P1：兑换的读-验-写全程持锁，防止并发双消费（flock 对进程与线程均互斥）
    with open(lock_path, "a+") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        ticket = _load_ticket(root_path, ticket_id, worktree_id=scope_wt)
        if ticket.consumed_at is not None:
            raise TicketError("ticket already consumed")
        if when > ticket.expires_at:
            raise TicketError("ticket expired")
        if not secrets.compare_digest(ticket.secret, secret):
            raise TicketError("ticket secret mismatch")
        if ticket.worktree_id and ticket.worktree_id != scope_wt:
            raise TicketError("ticket worktree mismatch")
        ident = load_identity(root_path)
        if ident and ticket.project_id not in ("", "unknown") and ticket.project_id != ident.project_id:
            raise TicketError("ticket project_id mismatch")
        if ticket.action != action:
            raise TicketError("ticket action mismatch")
        if ticket.input_fingerprint != input_fingerprint:
            raise TicketError("ticket input fingerprint mismatch")
        if task_id and ticket.task_id and ticket.task_id != task_id:
            raise TicketError("ticket task_id mismatch")
        if side_effect and side_effect not in ticket.allowed_side_effects:
            raise TicketError(f"side effect not allowed: {side_effect}")
        if expected_plan_digest and ticket.effective_plan_digest and \
                ticket.effective_plan_digest != expected_plan_digest:
            raise TicketError("ticket plan digest mismatch: 授权不属于当前冻结计划")
        if expected_phase and ticket.phase and ticket.phase != expected_phase:
            raise TicketError("ticket phase mismatch: 阶段授权不可跨阶段使用")
        ticket.consumed_at = when
        _save_ticket(root_path, ticket)
        return ticket


def phase_grant_fingerprint(*, phase: str, allowed_side_effects: list[str],
                            task_id: str = "") -> str:
    """阶段授权指纹（确定性；兑换方用同一参数重算）。"""
    raw = json.dumps({"phase": phase, "side_effects": sorted(allowed_side_effects),
                      "task_id": task_id}, ensure_ascii=False, sort_keys=True)
    return "phase-" + content_hash_safe(raw)


def issue_phase_grant(
    root: Path, *, phase: str, allowed_side_effects: list[str],
    task_id: str = "", effective_plan_digest: str = "",
    ttl_seconds: int = 300, issued_by: str = "sopctl",
) -> CapabilityTicket:
    """§10.4：同一阶段低风险动作共用一张短期授权（高风险不可逆动作仍单独收紧）。"""
    if not phase.strip():
        raise TicketError("phase grant 需要命名阶段")
    if not allowed_side_effects:
        raise TicketError("phase grant 需要非空副作用集合")
    return issue_ticket(
        root, action=f"phase:{phase}",
        input_fingerprint=phase_grant_fingerprint(
            phase=phase, allowed_side_effects=list(allowed_side_effects),
            task_id=task_id),
        allowed_side_effects=list(allowed_side_effects), task_id=task_id,
        ttl_seconds=ttl_seconds, issued_by=issued_by,
        effective_plan_digest=effective_plan_digest, phase=phase,
    )


def verify_ticket_for_admission(
    root: Path,
    *,
    ticket_id: str,
    secret: str,
    action: str,
    input_fingerprint: str,
    side_effect: str = "",
    task_id: str = "",
    worktree_id: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Adapter 在真实 admission point 核验授权：只读，不消费票据。

    供经 SOPCTL_TICKET_FILE handoff 拿到票据的子进程 adapter 调用；
     opaque 命令忽略该文件（由 bridge 代兑并在 receipt 明示）。
    """
    root_path = Path(root)
    scope_wt = worktree_id or ProjectScope(root_path, mode="discovery").worktree_id
    when = now or utcnow()
    ticket = _load_ticket(root_path, ticket_id, worktree_id=scope_wt)
    if when > ticket.expires_at:
        raise TicketError("ticket expired")
    if not secrets.compare_digest(ticket.secret, secret):
        raise TicketError("ticket secret mismatch")
    if ticket.action != action:
        raise TicketError("ticket action mismatch")
    if ticket.input_fingerprint != input_fingerprint:
        raise TicketError("ticket input fingerprint mismatch")
    if task_id and ticket.task_id and ticket.task_id != task_id:
        raise TicketError("ticket task_id mismatch")
    if side_effect and side_effect not in ticket.allowed_side_effects:
        raise TicketError(f"side effect not allowed: {side_effect}")
    return {"ticket_id": ticket.ticket_id, "verified": True,
            "consumed": ticket.consumed_at is not None,
            "effective_plan_digest": ticket.effective_plan_digest,
            "phase": ticket.phase}


def is_ticket_consumed(root: Path, ticket_id: str, worktree_id: str = "") -> bool:
    """只读：票据是否已被兑换（消费后验用；缺失视为未消费）。"""
    try:
        ticket = _load_ticket(root, ticket_id, worktree_id=worktree_id)
    except TicketError:
        return False
    return ticket.consumed_at is not None


def ticket_public_view(ticket: CapabilityTicket) -> dict[str, Any]:
    """Safe view for logs (excludes secret)."""
    data = ticket.model_dump(mode="json")
    data.pop("secret", None)
    return data

"""可信确认通道（WP-C3）：预览→批准一次性绑定，防重放、防跨项目、防伪造。

权限模型（诚实边界）：
- 确认凭据只能由 Agent 无法访问的用户侧签发才算“已验证的人类确认”。
  本地 CLI 没有宿主 UI 通道，因此所有经 CLI 到达的批准一律记为
  claimed（自称），人类在场为 UNPROVEN——如实标注，不伪装。
- 本模块保证的是工作流绑定：一次预览（preview_id）只能批准与其绑定的
  具体变更（rule_id + 内容摘要 + 项目 + 用途 + 期限），一次性消费，
  过期/重放/跨项目/摘要不一致一律拒绝。
- 复用 tickets.py 的签发/绑定/消费（锁+单次消费+过期），不另起炉灶。
- 非交互 CI/迁移走维护者凭据（SOPCTL_MAINTAINER_TOKEN 文件路径），
  记录 via=maintainer-token，可审计；单靠 TTY 或把 secret 打到模型可见
  stdout 不构成人类证明（approve 要求 --secret-file，不接受命令行明文）。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

CONFIRM_ACTION = "authority.confirm"
CONFIRM_SIDE_EFFECT = "authority_change"
PENDING_TTL_SECONDS = 3600


class ConfirmationError(ValueError):
    pass


def change_digest(rule_id: str, statement: str, extra: dict[str, Any] | None = None) -> str:
    """变更内容摘要：rule_id + 规范化陈述 + 附加绑定字段。"""
    payload = {"rule_id": rule_id,
               "statement": " ".join(str(statement or "").split()),
               "extra": extra or {}}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return "chg-" + hashlib.sha256(raw).hexdigest()[:32]


def _pending_dir(root: Path) -> Path:
    return Path(root) / ".sopcontrol-local" / "confirmations"


def request_confirmation(
    root: Path | str, *, kind: str, subject_id: str, digest: str,
    purpose: str, project_id: str = "", ttl_seconds: int = PENDING_TTL_SECONDS,
    actor_claim: str = "",
) -> dict[str, Any]:
    """签发一次确认请求（预览）。返回绑定信息；secret 只写 0600 文件。"""
    from .tickets import issue_ticket

    root = Path(root)
    if not kind.strip() or not subject_id.strip():
        raise ConfirmationError("确认请求需要 kind 与 subject_id")
    if not digest.strip():
        raise ConfirmationError("确认请求需要变更内容摘要（不得批空白变更）")
    ticket = issue_ticket(
        root, action=CONFIRM_ACTION, input_fingerprint=digest,
        allowed_side_effects=[CONFIRM_SIDE_EFFECT],
        task_id=f"{kind}:{subject_id}",
        ttl_seconds=ttl_seconds, issued_by="sopctl-confirm",
        capability_binding=json.dumps(
            {"kind": kind, "subject_id": subject_id, "purpose": purpose,
             "project_id": project_id, "actor_claim": actor_claim},
            ensure_ascii=False, sort_keys=True),
    )
    d = _pending_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    record = {"confirmation_id": ticket.ticket_id, "kind": kind,
              "subject_id": subject_id, "change_digest": digest,
              "purpose": purpose, "project_id": project_id,
              "actor_claim": actor_claim, "expires_at": ticket.expires_at.isoformat(),
              "consumed": False,
              # 一次性 secret：仅此次返回（同 ticket issue 语义）。
              # 批准方自行存入 0600 文件；此处不落盘、不进日志。
              "secret_one_time": ticket.secret}
    show = {k: v for k, v in record.items()}
    (d / f"{ticket.ticket_id}.json").write_text(
        json.dumps({k: v for k, v in record.items() if k != "secret_one_time"},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return show


def _load_pending(root: Path, confirmation_id: str) -> dict[str, Any]:
    from .scope import validate_identifier

    validate_identifier(confirmation_id, kind="confirmation id")
    path = _pending_dir(Path(root)) / f"{confirmation_id}.json"
    if not path.is_file():
        raise ConfirmationError(f"未知确认请求: {confirmation_id}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ConfirmationError(f"确认记录损坏: {exc}") from exc


def _read_secret(secret_file: str) -> str:
    if not secret_file:
        raise ConfirmationError("批准需要 --secret-file（0600 文件），不接受命令行明文 secret")
    try:
        mode = os.stat(secret_file).st_mode & 0o777
    except OSError as exc:
        raise ConfirmationError(f"secret 文件不可读: {exc}") from exc
    if mode & 0o077:
        raise ConfirmationError(f"secret 文件权限过宽 ({oct(mode)})：必须仅所有者可读写")
    try:
        return Path(secret_file).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConfirmationError(f"secret 文件不可读: {exc}") from exc


def approve_confirmation(
    root: Path | str, confirmation_id: str, *, secret_file: str = "",
    expected_digest: str = "", expected_project_id: str = "",
    via: str = "user-channel", now: Optional[datetime] = None,
) -> dict[str, Any]:
    """批准（兑换，一次性）。成功返回批准记录（claimed，非已验证人类）。"""
    from .tickets import TicketError, redeem_ticket

    root = Path(root)
    pending = _load_pending(root, confirmation_id)
    if pending.get("consumed"):
        raise ConfirmationError(f"确认 {confirmation_id} 已被使用：重放拒绝")
    if expected_digest and pending["change_digest"] != expected_digest:
        raise ConfirmationError("变更摘要不一致：批准绑定的是另一份变更")
    if expected_project_id and pending.get("project_id") \
            and pending["project_id"] != expected_project_id:
        raise ConfirmationError("项目不一致：跨项目凭据拒绝")
    secret = _read_secret(secret_file)
    maintainer = os.environ.get("SOPCTL_MAINTAINER_TOKEN", "").strip()
    via_label = via
    redeem_secret = secret
    if maintainer and secret == maintainer:
        # 维护者凭据路径（CI/迁移）：凭据对上后，由本进程经 ticket store
        # 取票据 secret 完成兑换——绑定检查与单次消费照常，不跳过。
        from .tickets import _load_ticket

        via_label = "maintainer-token"
        try:
            stored = _load_ticket(root, confirmation_id)
        except Exception as exc:
            raise ConfirmationError(f"批准失败: 票据不存在: {exc}") from exc
        if stored.consumed_at is not None:
            raise ConfirmationError(f"确认 {confirmation_id} 已被使用：重放拒绝")
        redeem_secret = stored.secret
    try:
        redeem_ticket(
            root, ticket_id=confirmation_id, secret=redeem_secret,
            action=CONFIRM_ACTION, input_fingerprint=pending["change_digest"],
            side_effect=CONFIRM_SIDE_EFFECT,
            task_id=f"{pending['kind']}:{pending['subject_id']}",
            expected_project_id=expected_project_id,
            now=now,
        )
    except TicketError as exc:
        raise ConfirmationError(f"批准失败: {exc}") from exc
    pending["consumed"] = True
    (_pending_dir(root) / f"{confirmation_id}.json").write_text(
        json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"confirmation_id": confirmation_id, "kind": pending["kind"],
            "subject_id": pending["subject_id"],
            "change_digest": pending["change_digest"],
            "approved_via": via_label,
            "authority": "claimed",
            "human_presence": "UNPROVEN",
            "note": "本地 CLI 无法证明人类在场；无宿主可信通道时视为自称，需用户侧复核"}


def show_confirmation(root: Path | str, confirmation_id: str) -> dict[str, Any]:
    """只读查看确认请求状态（不消费）。"""
    return _load_pending(Path(root), confirmation_id)

"""Bridge P0：稳定 operation envelope + 挑战/重试/兑换/回执。

§3.1 operation_id 代表一次逻辑操作（挑战与重试不变），attempt_id 代表单次尝试；
指纹（§3.2）只含 integration/action/argv，不含时间、attempt、secret、ticket id。
本地只读动作（§4.4）不进入票据流程；票据型副作用挑战一次、重试一次、不无限签发。
"""
from __future__ import annotations

import hashlib
import json
import secrets
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .action_plane import build_envelope
from .model import utcnow
from .scope import validate_identifier
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

# envelope surface → 票据副作用类（自动分类用）。
_SURFACE_TO_SIDE = {
    "network": "network_request",
    "browser": "browser_session",
    "credential": "credential_use",
    "database": "database_write",
}

# 程序名 → 副作用类（argv 首词判定；envelope 只能看到 Bash 壳，必须看真实程序）。
# 未命中程序一律按本地 shell 执行——这是有意的 cooperating-operator 边界
# （见 AGENTS.md scope）：bridge 不是操作系统沙箱，本地 shell 即调用方本机。
_PROGRAM_TO_SIDE = {
    "curl": "network_request", "wget": "network_request",
    "ssh": "network_request", "scp": "network_request",
    "sftp": "network_request", "ftp": "network_request",
    "nc": "network_request",
    "psql": "database_write", "mysql": "database_write",
    "sqlite3": "database_write", "mongosh": "database_write",
    "redis-cli": "database_write",
    "chromium": "browser_session", "chrome": "browser_session",
    "google-chrome": "browser_session", "firefox": "browser_session",
    "playwright": "browser_session",
}

# sh 族 -c 包裹：看内层命令，不看 sh 壳（`sh -c "curl …"` 按 network 处理）。
_SHELL_WRAPPERS = frozenset({"sh", "bash", "dash", "zsh"})

# 本地低风险面：无票可执行（调用方自己的机器；非沙箱承诺）。
_LOCAL_SURFACES = frozenset({"shell", "filesystem_read", "search", "filesystem_write"})


def _program_side(argv: list[str]) -> str:
    """argv 首词程序名 → 副作用类；命中 sh 族 -c 则看内层首词。"""
    if not argv:
        return ""
    prog = str(argv[0]).split("/")[-1].lower()
    if prog in _SHELL_WRAPPERS:
        parts = [str(a) for a in argv[1:4]]
        if "-c" in parts:
            inner = parts[parts.index("-c") + 1].strip().split() if "-c" in parts[:-1] else []
            if inner:
                return _PROGRAM_TO_SIDE.get(inner[0].split("/")[-1].lower(), "")
            return ""
    return _PROGRAM_TO_SIDE.get(prog, "")


def classify_bridge_argv(integration_id: str, argv: list[str]) -> tuple[str, str]:
    """自动分类：先看 argv 首词程序名（sh -c 看内层），再回落 envelope。

    返回 (surface, side_effect|\"\")；都看不出返回 (\"unknown\", \"\")。
    """
    side = _program_side([str(a) for a in argv])
    if side:
        surface = next((s for s, v in _SURFACE_TO_SIDE.items() if v == side), "unknown")
        return surface, side
    command = " ".join(str(item) for item in argv)
    envelope = build_envelope(
        {"tool_name": "Bash", "tool_input": {"command": command}},
        harness="bridge",
        task_id=integration_id,
    )
    surface = envelope.surface or "unknown"
    return surface, _SURFACE_TO_SIDE.get(surface, "")


def canonical_payload(integration_id: str, action: str, argv: list[str]) -> dict[str, Any]:
    """§9.5 统一规范：bridge 动作并入 ActionEnvelope 分类机器。

    argv 合成为 shell 命令载荷，经 build_envelope 分类出 surface/operation/target，
    指纹基与 harness 侧完全同构——同一动作经任意 harness 到达，指纹一致。
    integration_id 入基（不同集成同名命令不混淆），仍不含时间/attempt/secret。
    """
    command = " ".join(str(item) for item in argv)
    envelope = build_envelope(
        {"tool_name": "Bash", "tool_input": {"command": command}},
        harness="bridge",
        task_id=integration_id,
    )
    return {
        "surface": envelope.surface,
        "operation": envelope.operation,
        "target": envelope.target,
        "integration_id": integration_id,
        "action": action,
    }


def _digest_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical_fingerprint(integration_id: str, action: str, argv: list[str]) -> str:
    """§3.2：可重建的规范指纹——不含时间/attempt/secret/ticket id。"""
    return "sha256:" + _digest_payload(canonical_payload(integration_id, action, argv))


def operation_id(integration_id: str, action: str, argv: list[str]) -> str:
    """与指纹同源的稳定逻辑操作 ID：挑战与重试天然一致。"""
    return "op-" + _digest_payload(canonical_payload(integration_id, action, argv))[:16]


def _rollback_path(root: Path) -> Path:
    return Path(root) / ".sopcontrol-local" / "bridge-rollback.json"


def _load_manifest(root: Path) -> dict[str, Any]:
    rollback = _rollback_path(root)
    if not rollback.exists():
        return {}
    return json.loads(rollback.read_text(encoding="utf-8"))


def _save_manifest(root: Path, manifest: dict[str, Any]) -> Path:
    rollback = _rollback_path(root)
    rollback.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return rollback


def install_wrapper(
    root: Path, *, integration_id: str, command: list[str], name: str = "",
) -> dict[str, Any]:
    """§9.4：生成透明 launcher 并记录回滚清单（.sopcontrol-local 内，可 remove）。"""
    root = Path(root)
    name = name or (integration_id.replace(".", "-") + "-bridge")
    validate_identifier(name, kind="bridge 安装名")
    bin_dir = root / ".sopcontrol-local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / name
    existed = launcher.exists()
    prev_backup: str | None = None
    prev_mode: int | None = None
    if existed:
        # 预存内容备份：remove 时恢复而不是删除（覆盖不等于拥有）。
        backup_dir = root / ".sopcontrol-local" / "bridge-rollback"
        backup_dir.mkdir(parents=True, exist_ok=True)
        prev_path = backup_dir / f"{name}.prev"
        prev_path.write_bytes(launcher.read_bytes())
        try:
            prev_mode = launcher.stat().st_mode & 0o7777
            prev_path.chmod(prev_mode)
        except OSError:
            pass
        prev_backup = str(prev_path)
    launcher.write_text(
        "#!/bin/sh\n"
        "# sopcontrol bridge launcher — remove via sopctl bridge remove\n"
        "exec "
        + " ".join(shlex.quote(str(part)) for part in command)
        + ' "$@"\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    manifest = _load_manifest(root)
    manifest[name] = {
        "integration_id": integration_id,
        "command": list(command),
        "files": [str(launcher)],
        "existed_before": existed,
        "prev_backup": prev_backup,
        "prev_mode": prev_mode,
    }
    rollback = _save_manifest(root, manifest)
    return {"name": name, "launcher": str(launcher), "rollback": str(rollback)}


def remove_wrapper(root: Path, *, name: str) -> dict[str, Any]:
    """§9.4 回滚：预存内容恢复原状；非预存才删除；清单内多余文件一并清理。"""
    root = Path(root)
    validate_identifier(name, kind="bridge 安装名")
    launcher = root / ".sopcontrol-local" / "bin" / name
    manifest = _load_manifest(root)
    existed_before = manifest.pop(name, None)
    _save_manifest(root, manifest)
    removed = False
    restored = False
    prev_backup = (existed_before or {}).get("prev_backup")
    prev_mode = (existed_before or {}).get("prev_mode")
    if prev_backup:
        try:
            prev_path = Path(prev_backup)
            if prev_path.is_file():
                launcher.write_bytes(prev_path.read_bytes())
                try:
                    launcher.chmod(int(prev_mode) if prev_mode else 0o755)
                except (OSError, ValueError, TypeError):
                    launcher.chmod(0o755)
                restored = True
        except OSError:
            restored = False
    if not restored:
        for f in [str(launcher)] + list((existed_before or {}).get("files") or []):
            try:
                p = Path(f)
                if p.exists() and p.is_file():
                    p.unlink()
                    removed = True
            except OSError:
                continue
        if launcher.exists():
            launcher.unlink()
            removed = True
    return {"name": name, "removed": removed, "restored": restored,
            "existed_before": (existed_before or {}).get("existed_before")}


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
    effective_plan_digest: str = "",
    phase: str = "",
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
        effective_plan_digest=effective_plan_digest,
        phase=phase,
    )


def challenge_admission(
    root: Path,
    *,
    integration_id: str,
    action: str,
    argv: list[str],
    side_effect: str,
    task_id: str = "",
    ttl_seconds: int = 900,
    effective_plan_digest: str = "",
    phase: str = "",
) -> dict[str, Any]:
    """签发 + 落 handoff（不兑换、不执行）：兑换只能发生在 admission 点。

    返回 {ticket_id, handoff, fingerprint, operation_id}（无 secret 对象；
    secret 只在 0600 handoff 文件内）。
    """
    root = Path(root)
    argv = [str(item) for item in argv]
    fingerprint = canonical_fingerprint(integration_id, action, argv)
    op_id = operation_id(integration_id, action, argv)
    ticket = challenge_ticket(
        root, integration_id=integration_id, action=action,
        input_fingerprint=fingerprint, side_effect=side_effect,
        task_id=task_id, ttl_seconds=ttl_seconds,
        effective_plan_digest=effective_plan_digest, phase=phase,
    )
    handoff_path, _ = _write_ticket_handoff(root, ticket, op_id)
    return {"ticket_id": ticket.ticket_id, "handoff": handoff_path,
            "input_fingerprint": fingerprint, "operation_id": op_id,
            "ticket": ticket_public_view(ticket)}


def admit_ticket(
    root: Path | str | None,
    *,
    ticket_file: str,
    integration_id: str,
    action: str,
    argv: list[str],
    side_effect: str,
    task_id: str = "",
    expected_plan_digest: str = "",
    expected_phase: str = "",
) -> dict[str, Any]:
    """在真实 admission 点兑换（合作 adapter/已安装入口调用；只兑一次）。

    票据 id+secret 只从 0600 handoff 文件读，不经 argv/环境传 secret。
    指纹由 (integration, action, argv) 重算——输入被改即拒。
    root 为空时取 handoff 内记录的签发根（子进程 cwd 可能与签发根不同）。
    """
    try:
        payload = json.loads(Path(ticket_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TicketError(f"handoff 票据不可读: {exc}")
    if root is None or str(root) == "":
        root = payload.get("root") or Path.cwd()
    root = Path(root)
    argv = [str(item) for item in argv]
    fingerprint = canonical_fingerprint(integration_id, action, argv)
    ticket = redeem_ticket(
        root,
        ticket_id=str(payload.get("ticket_id") or ""),
        secret=str(payload.get("secret") or ""),
        action=action,
        input_fingerprint=fingerprint,
        side_effect=side_effect,
        task_id=task_id,
        worktree_id=str(payload.get("worktree_id") or ""),
        expected_plan_digest=expected_plan_digest,
        expected_phase=expected_phase,
    )
    return {"admitted": True, "ticket_id": ticket.ticket_id,
            "operation_id": str(payload.get("operation_id") or "")}


def _ticket_consumed(root: Path, ticket_id: str) -> bool:
    """后验：票据是否已被兑换（run 的消费后验用，只读）。"""
    from .tickets import _load_ticket

    try:
        ticket = _load_ticket(root, ticket_id)
    except TicketError:
        return False
    return ticket.consumed_at is not None


def _scrub(text: str, secrets_: list[str]) -> str:
    """回执脱敏：已知 secret 精确替换（子进程可能回显 handoff 内容）。"""
    for secret in secrets_:
        if secret:
            text = text.replace(secret, "***")
    return text


def _write_ticket_handoff(root: Path, ticket: Any, operation_id: str) -> tuple[str, str]:
    """票据 handoff（§2.3 临时安全文件描述符通道）。

    secret 只进 0600 文件，不进环境变量/进程表/日志；子进程 adapter 可凭
    文件向 verify_ticket_for_admission 自证；跑后删除。
    """
    import os as _os
    import stat as _stat

    d = Path(root) / ".sopcontrol-local" / "tickets" / ".handoff"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{ticket.ticket_id}.json"
    path.write_text(json.dumps({
        "ticket_id": ticket.ticket_id,
        "secret": ticket.secret,
        "action": ticket.action,
        "input_fingerprint": ticket.input_fingerprint,
        "operation_id": operation_id,
        "root": str(root),
        "worktree_id": ticket.worktree_id,
    }, ensure_ascii=False), encoding="utf-8")
    _os.chmod(path, _stat.S_IRUSR | _stat.S_IWUSR)
    return str(path), ticket.ticket_id


def run_bridge(
    root: Path,
    *,
    integration_id: str,
    action: str,
    argv: list[str],
    side_effect: str = "",
    task_id: str = "",
    ttl_seconds: int = 900,
    policy_pack: str = "",
    effective_plan_digest: str = "",
    phase: str = "",
) -> dict[str, Any]:
    """§4.1 挑战-handoff-执行-消费后验的闭环（兑换只发生在 admission 点）。

    副作用判定 fail-closed（见分类逻辑）；票据由子进程 adapter 经 handoff
    在真实入口兑换（`bridge admit`），bridge 只签发、递送、后验消费——
    子进程不兑换即视为未通过（executed=false），不存在"不校验也通过"。
    回执做 secret 洗脱；redemption_point 如实标注。
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
        "redemption_point": "none",
        "ticket_handoff": "",
        "policy_pack": policy_pack or "",
        "policy_decision": "",
    }

    def _refuse(error: str) -> dict[str, Any]:
        receipt["executed"] = False
        receipt["error"] = error
        return receipt

    surface, classified = classify_bridge_argv(integration_id, argv)
    if policy_pack:
        from .policy_pack import PackError, load_pack, match_breakers

        try:
            pack = load_pack(policy_pack)
        except PackError as exc:
            return _refuse(f"policy pack 非法: {exc}")
        attrs = {"command": " ".join(argv), "integration": integration_id,
                 "action": action}
        hits = match_breakers(pack, surface=surface, attrs=attrs)
        denied = [h for h in hits if h.decision == "deny"]
        if denied:
            receipt["policy_decision"] = f"deny:{denied[0].id}"
            return _refuse(f"policy pack 阻断 [{denied[0].id}]：{denied[0].reason}")
        asked = [h for h in hits if h.decision == "ask"]
        if asked:
            receipt["policy_decision"] = f"ask:{asked[0].id}"
            # ask 强制走票：无票据类时按分类（无分类则拒绝）。
            if not side_effect and not classified:
                return _refuse(
                    f"policy pack 要求授权 [{asked[0].id}] 但动作无法分类："
                    f"请声明 --side-effect")
            if not side_effect:
                side_effect = classified
        else:
            receipt["policy_decision"] = "allow (no breaker hit)"
    effective = side_effect
    if side_effect:
        if side_effect in TICKET_REQUIRED_SIDES:
            # 可证伪才拒绝：分类出另一票据类说明声明撒谎；分类不出时走票据
            # 流程并如实记录声明（receipt 含 argv 可审计）。
            if classified and classified != side_effect:
                return _refuse(
                    f"side_effect {side_effect!r} 与 envelope 分类 {classified!r} 不符：拒绝执行")
        else:
            if not classified:
                return _refuse(
                    f"未知副作用声明 {side_effect!r} 且 envelope 无法分类 "
                    f"(surface={surface})：拒绝执行，请声明 --side-effect")
            if classified != side_effect:
                return _refuse(
                    f"side_effect {side_effect!r} 与 envelope 分类 {classified!r} 不符：拒绝执行")
            effective = classified
    else:
        if action in READ_ONLY_ACTIONS:
            if classified and classified in TICKET_REQUIRED_SIDES:
                effective = classified
            elif surface not in _LOCAL_SURFACES and surface != "unknown":
                return _refuse(
                    f"只读动作 {action!r} 触及非本地 surface={surface}："
                    f"请显式声明 --side-effect")
            elif surface == "unknown":
                return _refuse(
                    f"只读动作 {action!r} 无法分类（surface=unknown）：拒绝执行")
        else:
            if not classified:
                return _refuse(
                    f"动作 {action!r} 未声明副作用且 envelope 无法分类 "
                    f"(surface={surface})：拒绝执行，请声明 --side-effect")
            effective = classified

    receipt["side_effect"] = effective or "none"
    ticket_id = ""
    handoff_path = ""
    if effective in TICKET_REQUIRED_SIDES:
        issued = challenge_admission(
            root,
            integration_id=integration_id,
            action=action,
            argv=argv,
            side_effect=effective,
            task_id=task_id,
            ttl_seconds=ttl_seconds,
            effective_plan_digest=effective_plan_digest,
            phase=phase,
        )
        ticket_id = issued["ticket_id"]
        handoff_path = issued["handoff"]
        receipt["challenge_count"] = 1
        receipt["ticket"] = issued["ticket"]
        receipt["ticket_handoff"] = handoff_path
        receipt["redemption_point"] = "pending-child-admission"

    import os as _os

    env = dict(_os.environ)
    if handoff_path:
        env["SOPCTL_TICKET_FILE"] = handoff_path
    scrub_secrets: list[str] = []
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=600, env=env)
    finally:
        if handoff_path:
            try:
                # 脱敏用：子进程可能回显 handoff 内容，精确替换 secret（内存内，不落盘）。
                payload = json.loads(Path(handoff_path).read_text(encoding="utf-8"))
                if payload.get("secret"):
                    scrub_secrets.append(str(payload["secret"]))
            except (OSError, ValueError):
                pass
            try:
                Path(handoff_path).unlink()
            except OSError:
                pass
            receipt["ticket_handoff"] += " (removed after run)"
    if ticket_id and not _ticket_consumed(root, ticket_id):
        receipt["executed"] = False
        receipt["error"] = (
            "admission 未兑换：子进程未在真实入口兑换票据——"
            "业务入口未受控。合作 adapter 应经 SOPCTL_TICKET_FILE 调用 "
            "sopctl bridge admit；裸命令请先 sopctl bridge install 生成入口")
        receipt["redemption_point"] = "none (admission missing)"
    else:
        if ticket_id:
            receipt["redemption_point"] = f"child-admission ({ticket_id})"
        receipt["executed"] = True
        receipt["exit_code"] = proc.returncode
    receipt["stdout_tail"] = _scrub(proc.stdout[-400:], scrub_secrets)
    receipt["stderr_tail"] = _scrub(proc.stderr[-400:], scrub_secrets)
    return receipt

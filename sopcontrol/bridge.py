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

# 本地低风险面：无票可执行（调用方自己的机器；非沙箱承诺）。
_LOCAL_SURFACES = frozenset({"shell", "filesystem_read", "search", "filesystem_write"})


def classify_bridge_argv(integration_id: str, argv: list[str]) -> tuple[str, str]:
    """自动分类：先看 argv 首词程序名，再回落 envelope（Bash 壳只能看到 shell）。

    返回 (surface, side_effect|\"\")；都看不出返回 (\"unknown\", \"\")。
    """
    if argv:
        prog = str(argv[0]).split("/")[-1].lower()
        if prog in _PROGRAM_TO_SIDE:
            side = _PROGRAM_TO_SIDE[prog]
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
    if existed:
        # 预存内容备份：remove 时恢复而不是删除（覆盖不等于拥有）。
        backup_dir = root / ".sopcontrol-local" / "bridge-rollback"
        backup_dir.mkdir(parents=True, exist_ok=True)
        prev_path = backup_dir / f"{name}.prev"
        prev_path.write_bytes(launcher.read_bytes())
        try:
            import stat as _stat

            prev_path.chmod(launcher.stat().st_mode & 0o7777)
        except OSError:
            pass
        prev_backup = str(prev_path)
    launcher.write_text(
        "#!/bin/sh\n"
        "# sopcontrol bridge launcher — remove via sopctl bridge remove\n"
        "exec "
        + " ".join(json.dumps(part) for part in command)
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
    if prev_backup:
        try:
            prev_path = Path(prev_backup)
            if prev_path.is_file():
                launcher.write_bytes(prev_path.read_bytes())
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
) -> dict[str, Any]:
    """§4.1 挑战-重试-兑换-回执的最小闭环（进程内 admission point）。

    副作用判定 fail-closed：显式 side_effect 必须与 envelope 自动分类一致；
    未声明且非只读动作按分类决定（高影响进票据流程，未知分类直接拒绝）；
    READ_ONLY_ACTIONS 只读动作用分类低风险才免票直行。
    票据经 0600 handoff 文件递子进程（跑后删除）；receipt 永不含 secret；
    redemption_point 如实标注兑换位置（不透明子进程由 bridge 代兑并明示）。
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
    }

    def _refuse(error: str) -> dict[str, Any]:
        receipt["executed"] = False
        receipt["error"] = error
        return receipt

    surface, classified = classify_bridge_argv(integration_id, argv)
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
    ticket_model = None
    handoff_path = ""
    if effective in TICKET_REQUIRED_SIDES:
        ticket_model = challenge_ticket(
            root,
            integration_id=integration_id,
            action=action,
            input_fingerprint=envelope["input_fingerprint"],
            side_effect=effective,
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
                side_effect=effective,
                task_id=task_id,
                worktree_id=ticket_model.worktree_id,
            )
        except TicketError as exc:
            receipt["executed"] = False
            receipt["error"] = f"ticket redemption failed: {exc}"
            return receipt
        # 不透明子进程由 bridge 代兑（明示）；handoff 文件供合作 adapter 在真实
        # 入口凭 verify_ticket_for_admission 自证；secret 永不进 receipt/日志。
        receipt["redemption_point"] = "bridge (opaque subprocess; adapters verify via handoff)"
        handoff_path, _ = _write_ticket_handoff(root, ticket_model, envelope["operation_id"])
        receipt["ticket_handoff"] = handoff_path

    import os as _os

    env = dict(_os.environ)
    if handoff_path:
        env["SOPCTL_TICKET_FILE"] = handoff_path
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=600, env=env)
    finally:
        if handoff_path:
            try:
                Path(handoff_path).unlink()
            except OSError:
                pass
            receipt["ticket_handoff"] += " (removed after run)"
    receipt["executed"] = True
    receipt["exit_code"] = proc.returncode
    receipt["stdout_tail"] = proc.stdout[-400:]
    receipt["stderr_tail"] = proc.stderr[-400:]
    return receipt

    proc = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    receipt["executed"] = True
    receipt["exit_code"] = proc.returncode
    receipt["stdout_tail"] = proc.stdout[-400:]
    receipt["stderr_tail"] = proc.stderr[-400:]
    if ticket_model is not None:
        receipt["ticket_model"] = ticket_model
    return receipt

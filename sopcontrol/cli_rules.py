"""CLI：规则登记与生命周期。"""
from __future__ import annotations

import sys
from pathlib import Path

from .cli_common import *  # noqa: F403
from .conflict import find_conflicts
from .model import Modality, RiskLevel, Rule, RuleStatus, SourceRef
from .registry import Registry, RegistryError

__all__ = [
    "cmd_rule_add",
    "cmd_rule_list",
    "cmd_rule_accept",
    "cmd_rule_attest",
    "cmd_rule_retire",
]



def cmd_rule_add(args) -> int:
    from .conflict import find_conflicts
    from .harness import GUARD_IDS

    root = _project(args.path)
    reg = Registry(root / ".sopcontrol" / "rules" / "registry.yaml")

    # guard 名写错不能静默收下：拦截器永远不会用这个名字留痕，规则就永远卡在
    # 「声明了 guard 却拿不到 trace」，而错因是一个字母。当场拒比事后查判定便宜。
    guard_ids = list(getattr(args, "guard_id", None) or [])
    unknown = [g for g in guard_ids if g not in GUARD_IDS]
    if unknown:
        print(
            f"错误: 未知 guard id {unknown}；拦截器已声明的是 {sorted(GUARD_IDS)}",
            file=sys.stderr,
        )
        return 2

    rule = Rule(
        rule_id=args.id,
        statement=args.statement,
        modality=Modality(args.modality),
        status=RuleStatus(args.status),
        scope=args.scope,
        owner=args.owner,
        risk=RiskLevel(args.risk),
        source=SourceRef(type=args.source_type, ref=args.source_ref),
        consumer_markers=list(args.consumer_marker or []),
        legacy_markers=list(getattr(args, "legacy_marker", None) or []),
        state_markers=list(getattr(args, "state_marker", None) or []),
        guard_ids=guard_ids,
        tags=list(args.tag or []),
    )
    if rule.status == RuleStatus.accepted:
        conflicts = find_conflicts(rule, reg.load())
        if conflicts:
            detail = "；".join(c["reason"] for c in conflicts)
            print(f"错误: 规则冲突（14.1 场景10）：{detail}", file=sys.stderr)
            return 2
    reg.add(rule)
    print(f"已登记规则 {rule.rule_id} [{rule.status.value}]：{rule.statement}")
    if rule.status == RuleStatus.accepted:
        print("注意：规则已直接置为 accepted；常规流程应从 proposed 出发，经确认后 accept")
    return 0



def cmd_rule_list(args) -> int:
    root = _project(args.path)
    rules = Registry(root / ".sopcontrol" / "rules" / "registry.yaml").load()
    if not rules:
        print("注册表为空")
        return 0
    print(f"{'RULE':16} {'状态':10} {'强度':9} {'吸收标记':24} 陈述")
    for r in rules:
        markers = ",".join(r.consumer_markers) or "-"
        print(f"{r.rule_id:16} {r.status.value:10} {r.modality.value:9} {markers:24} {r.statement[:40]}")
    return 0



def cmd_rule_accept(args) -> int:
    root = _project(args.path)
    rule = Registry(root / ".sopcontrol" / "rules" / "registry.yaml").transition(
        args.rule_id, RuleStatus.accepted
    )
    print(f"{rule.rule_id} 已接受（accepted_at={rule.accepted_at}）；下一步 sopctl audit 检查吸收")
    return 0



def cmd_rule_retire(args) -> int:
    """永久退出规则：内容寻址预览确认，registry 与平台投影失败时一并回滚。"""
    root = _project(args.path)
    registry = Registry(root / ".sopcontrol" / "rules" / "registry.yaml")
    action = args.sub
    replacement = str(getattr(args, "replacement", "") or "")
    supplied = str(getattr(args, "confirm_preview", "") or "")
    if not supplied:
        preview = registry.retirement_preview(
            args.rule_id,
            action=action,
            reason=args.reason,
            actor=args.by,
            replacement=replacement,
        )
        print(f"规则退出预览: {args.rule_id} → {action}")
        if replacement:
            print(f"  replacement: {replacement}")
        print(f"  reason: {preview['reason']}")
        print(f"  actor: {preview['actor']}")
        print(f"  受影响消费者: {', '.join(preview['consumer_markers']) or '无'}")
        print(f"  受影响 guard: {', '.join(preview['guard_ids']) or '无'}")
        from .task import TaskStatus, TaskStore

        terminal = {TaskStatus.blocked, TaskStatus.failed_unverified, TaskStatus.delivered}
        affected_tasks = [
            f"{task.task_id}[{task.status.value}]"
            for task in TaskStore(root).list_all()
            if task.status not in terminal and args.rule_id in task.contract.required_rules
        ]
        print(f"  受影响任务: {', '.join(affected_tasks) or '无'}")
        print("  投影目标: AGENTS.md, CLAUDE.md")
        print(f"  preview_id: {preview['preview_id']}")
        print("未修改任何文件；确认时原样重跑并带 --confirm-preview <preview_id>")
        return 0

    tracked = [registry.path, root / "AGENTS.md", root / "CLAUDE.md"]
    with registry.exclusive():
        before = {path: path.read_bytes() if path.exists() else None for path in tracked}
        try:
            retired = registry.confirm_retirement(
                args.rule_id,
                action=action,
                reason=args.reason,
                actor=args.by,
                preview_id=supplied,
                replacement=replacement,
            )
            from .project import write_all_projections

            write_all_projections(root)
        except Exception as exc:  # registry 与投影构成一个用户可见事务
            for path, content in before.items():
                try:
                    if content is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(content)
                except OSError:
                    pass
            if isinstance(exc, RegistryError):
                raise
            print(f"错误: 规则退出未完成，registry 与投影已回滚（{exc}）", file=sys.stderr)
            return 2

    suffix = f"；由 {replacement} 接管" if replacement else ""
    print(
        f"规则 {retired.rule_id} 已永久置为 {retired.status.value}{suffix}；"
        f"retirement_id={retired.retirement_id}"
    )
    print("AGENTS.md 与 CLAUDE.md 已同步；历史记录保留，但该规则不再参与当前执法")
    return 0



def cmd_rule_attest(args) -> int:
    from .attest import AttestError, record_attestation

    root = _project(args.path)
    try:
        rule = record_attestation(
            root, args.rule_id, bypass_note=args.bypass_note, by=args.by
        )
    except AttestError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    print(
        f"{rule.rule_id} 已确认：绑定 {rule.source.ref} @ {rule.source_hash}"
        f"（by={rule.attested_by}）"
    )
    print("源文档一改，下轮 audit 自动撤销 enforced；届时需复核规则并重新 attest")
    return 0


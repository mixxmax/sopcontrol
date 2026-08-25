"""CLI：规则登记与生命周期。"""
from __future__ import annotations

import sys
from pathlib import Path

from .cli_common import *  # noqa: F403
from .conflict import find_conflicts
from .model import Modality, RiskLevel, Rule, RuleStatus, SourceRef
from .registry import Registry

__all__ = ["cmd_rule_add", "cmd_rule_list", "cmd_rule_accept"]



def cmd_rule_add(args) -> int:
    from .conflict import find_conflicts

    root = _project(args.path)
    reg = Registry(root / ".sopcontrol" / "rules" / "registry.yaml")
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


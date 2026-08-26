"""CLI：规则登记与生命周期。"""
from __future__ import annotations

import sys
from pathlib import Path

from .cli_common import *  # noqa: F403
from .conflict import find_conflicts
from .model import Modality, RiskLevel, Rule, RuleStatus, SourceRef
from .registry import Registry

__all__ = ["cmd_rule_add", "cmd_rule_list", "cmd_rule_accept", "cmd_rule_attest"]



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


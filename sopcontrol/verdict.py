"""纯函数判定器：无 I/O、无 LLM、无隐藏状态（宪法属性，tests/constitution/test_purity.py 挑衅验证）。

判定不信任检测器：吸收等级由判定器从 Evidence 独立推导，Finding 仅被引用。
"""
from __future__ import annotations

from .context import is_test_path
from .model import (
    Absorption,
    Evidence,
    Finding,
    Modality,
    Rule,
    RuleStatus,
    Verdict,
)

GOVERNANCE_ACTIVE = {
    RuleStatus.accepted,
    RuleStatus.compiled,
    RuleStatus.activated,
    RuleStatus.monitored,
}
HARD_MODALITIES = {Modality.MUST, Modality.MUST_NOT}


def marker_hit(ev: Evidence, markers: list[str]) -> bool:
    """标记命中判定：.py 以 AST 引用为准（注释不算）；其他表面用 grep 标识符。"""
    if ev.kind == "ast_scan.references":
        return any(m in (ev.observed or []) for m in markers)
    if ev.kind == "code_scan.identifiers" and not ev.subject.endswith(".py"):
        return any(m in (ev.observed or []) for m in markers)
    return False


def consumer_evidence(rule: Rule, evidence: list[Evidence]) -> tuple[list[Evidence], list[Evidence]]:
    """返回 (生产路径消费者证据, 测试路径消费者证据)。"""
    prod, test = [], []
    for ev in evidence:
        if marker_hit(ev, rule.consumer_markers):
            (test if is_test_path(ev.subject) else prod).append(ev)
    return prod, test


def legacy_evidence(rule: Rule, evidence: list[Evidence]) -> list[Evidence]:
    """生产路径上仍然存活的旧入口证据（测试路径中出现不算绕过）。"""
    if not rule.legacy_markers:
        return []
    hits = []
    for ev in evidence:
        if marker_hit(ev, rule.legacy_markers) and not is_test_path(ev.subject):
            hits.append(ev)
    return hits


def evaluate_rule(rule: Rule, evidence: list[Evidence], findings: list[Finding]) -> Verdict:
    related = [f for f in findings if f.rule_id == rule.rule_id]
    fids = [f.finding_id for f in related]

    if rule.status not in GOVERNANCE_ACTIVE:
        return Verdict(
            rule_id=rule.rule_id,
            status="unknown",
            absorption=None,
            reason=f"规则处于 {rule.status.value}，尚未被接受，没有吸收义务",
            next_action=f"运行 sopctl rule accept {rule.rule_id} 接受它，或保持观察",
            finding_ids=fids,
        )

    if rule.modality not in HARD_MODALITIES:
        return Verdict(
            rule_id=rule.rule_id,
            status="unknown",
            absorption=None,
            reason=f"{rule.modality.value} 规则按手册 4.4 不进入硬吸收判定（落点为建议/评分，不阻断）",
            next_action="无需动作",
            finding_ids=fids,
        )

    prod, test = consumer_evidence(rule, evidence)
    base = _absorption_verdict(rule, prod, test, fids)

    legacy = legacy_evidence(rule, evidence)
    if legacy:
        legacy_names = ", ".join(rule.legacy_markers)
        return base.model_copy(
            update={
                "status": "fail",
                "reason": f"生产路径仍存在旧入口 [{legacy_names}]，受控入口可被绕过（{base.reason}）",
                "next_action": "关闭旧入口，或将其改为委托受控入口后移出 legacy_markers",
                "evidence_ids": base.evidence_ids + [e.evidence_id for e in legacy],
            }
        )
    return base


def _absorption_verdict(rule: Rule, prod: list[Evidence], test: list[Evidence], fids: list[str]) -> Verdict:
    if rule.state_markers and not rule.consumer_markers:
        return Verdict(
            rule_id=rule.rule_id,
            status="unknown",
            absorption=None,
            reason="状态类规则：吸收等级不适用，由 state_health 模式评估（write_only/parallel/absent）",
            next_action="关注 audit 输出中的 state_health findings",
            finding_ids=fids,
        )

    if not rule.consumer_markers:
        return Verdict(
            rule_id=rule.rule_id,
            status="unknown",
            absorption=None,
            reason="规则未声明 consumer_markers，无法判定吸收；'什么算消费者'由语料逐模式经验回答，不由宏大定义回答",
            next_action=f"为 {rule.rule_id} 声明 consumer_markers（什么符号/入口算生产消费者）",
            finding_ids=fids,
        )

    markers = ", ".join(rule.consumer_markers)

    if not prod:
        hint = "；消费者标记仅见于测试路径，疑似测试 helper 掩盖生产缺口" if test else ""
        return Verdict(
            rule_id=rule.rule_id,
            status="gap",
            absorption=Absorption.documented,
            reason=f"已接受的 {rule.modality.value} 规则在生产路径没有消费者 [{markers}]{hint}",
            next_action=f"为 {rule.rule_id} 接线生产消费者，或将其降级回 proposed",
            finding_ids=fids,
        )

    if not test:
        return Verdict(
            rule_id=rule.rule_id,
            status="gap",
            absorption=Absorption.wired,
            reason=f"生产消费者已接线 [{markers}]，但测试路径没有回归证据",
            next_action=f"为 {rule.rule_id} 补充负向回归测试（例如：无确认直接写表必须被拒绝）",
            evidence_ids=[e.evidence_id for e in prod],
            finding_ids=fids,
        )

    return Verdict(
        rule_id=rule.rule_id,
        status="pass",
        absorption=Absorption.wired_and_tested,
        reason=f"消费者与回归证据齐备 [{markers}]；enforced 还需要运行时 trace 证据（手册 6.5 七条件），v0 不颁发",
        next_action="无",
        evidence_ids=[e.evidence_id for e in prod + test],
        finding_ids=fids,
    )


def evaluate_all(rules: list[Rule], evidence: list[Evidence], findings: list[Finding]) -> list[Verdict]:
    return [evaluate_rule(r, evidence, findings) for r in rules]

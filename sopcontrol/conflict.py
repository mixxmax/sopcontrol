"""规则冲突检测（手册 14.1 场景10）。

高影响新规则与历史规则在同一消费者标记上模态相反 → 冲突。
纯函数；接受前必须先 supersede/拒绝，不得静默并存。
"""
from __future__ import annotations

from .model import Modality, Rule, RuleStatus

GOVERNANCE_ACTIVE = {
    RuleStatus.accepted,
    RuleStatus.compiled,
    RuleStatus.activated,
    RuleStatus.monitored,
}
HARD = {Modality.MUST, Modality.MUST_NOT}


def modality_conflicts(a: Modality, b: Modality) -> bool:
    return {a, b} == {Modality.MUST, Modality.MUST_NOT}


def find_conflicts(candidate: Rule, rules: list[Rule]) -> list[dict]:
    """返回与 candidate 冲突的活跃硬规则摘要列表。"""
    if candidate.modality not in HARD or not candidate.consumer_markers:
        return []
    out = []
    cand_markers = set(candidate.consumer_markers)
    for other in rules:
        if other.rule_id == candidate.rule_id:
            continue
        if other.status not in GOVERNANCE_ACTIVE or other.modality not in HARD:
            continue
        if candidate.rule_id in (other.supersedes or []):
            continue  # 显式取代关系，不算未治理冲突
        if other.rule_id in (candidate.supersedes or []):
            continue
        overlap = cand_markers & set(other.consumer_markers or [])
        if not overlap:
            continue
        if modality_conflicts(candidate.modality, other.modality):
            out.append({
                "other_id": other.rule_id,
                "overlap": sorted(overlap),
                "candidate_modality": candidate.modality.value,
                "other_modality": other.modality.value,
                "reason": (
                    f"{candidate.rule_id}({candidate.modality.value}) 与 "
                    f"{other.rule_id}({other.modality.value}) 在消费者 "
                    f"[{', '.join(sorted(overlap))}] 上模态相反"
                ),
            })
    return out

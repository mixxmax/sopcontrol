"""WP-B1：统一选择评估入口——效果类型、三桶、冲突、标识链。"""
from __future__ import annotations

import json

from sopcontrol.action_plane import commit_action_result
from sopcontrol.cli import main
from sopcontrol.model import (
    ActivationSelector,
    Modality,
    Rule,
    RuleStatus,
    SourceRef,
)
from sopcontrol.rule_select import (
    decide_action_with_rules,
    rule_effect_kind,
    select_rules_for_action,
)


def _rule(rule_id="R-1", *, modality=Modality.MUST, status=RuleStatus.compiled,
          rule_class="dynamic_sop", activation=None, guard_ids=(),
          consumer_markers=(), state_markers=(), scope_paths=()):
    from datetime import datetime, timezone

    from sopcontrol.model import RuleLifecycleEvent

    paths = list(scope_paths)
    events = []
    revision = 0
    at = None
    if paths:
        at = datetime.now(timezone.utc)
        events = [RuleLifecycleEvent(
            action="narrow", actor="test", reason="test scope",
            at=at, preview_id=f"pv-{rule_id}", revision=1,
            before_scope=[], after_scope=paths)]
        revision = 1
    return Rule(rule_id=rule_id, statement=f"规则{rule_id}",
                modality=modality, status=status, rule_class=rule_class,
                source=SourceRef(ref="s"),
                activation=activation or ActivationSelector(),
                guard_ids=list(guard_ids),
                consumer_markers=list(consumer_markers),
                state_markers=list(state_markers),
                scope_paths=paths,
                lifecycle_events=events,
                lifecycle_revision=revision,
                effective_since=at)


def test_effect_kind_from_existing_bindings():
    assert rule_effect_kind(_rule(guard_ids=["GUARD-CONTROLLER-BASH"])) == "controlled_entry"
    assert rule_effect_kind(_rule(consumer_markers=["probe-x"])) == "host_check"
    assert rule_effect_kind(_rule(
        activation=ActivationSelector(actions=["a"]))) == "scope"
    assert rule_effect_kind(_rule(state_markers=["s"])) == "state"
    # 旧数据：无任何绑定 → unwired（照选不照降，见下）
    assert rule_effect_kind(_rule()) == "unwired"


def test_unwired_still_selected_but_labeled():
    sel = select_rules_for_action([_rule()], {})
    assert [s.rule_id for s in sel.selected] == ["R-1"]
    assert sel.unwired == ["R-1"]
    assert sel.selected[0].effect == "unwired"


def test_three_buckets_preserved():
    sel = select_rules_for_action(
        [_rule("A", activation=ActivationSelector(actions=["x"]))], {})
    assert sel.selected == [] and sel.not_applicable == []
    assert len(sel.unproven) == 1 and "无法证明 action" in sel.unproven[0]["reason"]
    sel2 = select_rules_for_action(
        [_rule("A", activation=ActivationSelector(actions=["x"]))],
        {"action": "y"})
    assert sel2.selected == [] and sel2.unproven == [] and len(sel2.not_applicable) == 1


def test_conflict_must_vs_must_not_asks():
    a = _rule("A-MUST", modality=Modality.MUST,
              activation=ActivationSelector(actions=["audit"]),
              scope_paths=["docs/"])
    b = _rule("B-MUSTNOT", modality=Modality.MUST_NOT,
              activation=ActivationSelector(actions=["audit"]),
              scope_paths=["docs/"])
    sel = select_rules_for_action([a, b], {"action": "audit"})
    assert len(sel.conflicts) == 1
    assert sel.conflicts[0]["rule_a"] == "A-MUST"
    assert "需用户决定" in sel.conflicts[0]["reason"]
    decision = decide_action_with_rules(
        [a, b], {"tool_name": "Read", "tool_input": {"file_path": "docs/x.md"}},
        {"action": "audit"})
    assert decision.decision == "ask"
    assert "A-MUST" in decision.rule_ids and "B-MUSTNOT" in decision.rule_ids
    assert decision.selection_evidence.startswith("sel-")


def test_no_conflict_when_scopes_disjoint():
    a = _rule("A", modality=Modality.MUST, scope_paths=["docs/"])
    b = _rule("B", modality=Modality.MUST_NOT, scope_paths=["src/"])
    sel = select_rules_for_action([a, b], {})
    assert sel.conflicts == []


def test_identifier_chain_select_decide_evidence(tmp_path, monkeypatch):
    """同一标识链：selected rule → decision.rule_ids → 落账回读同一标识。"""
    from sopcontrol.activity_log import load_activity

    monkeypatch.chdir(tmp_path)
    assert main(["init", str(tmp_path)]) == 0
    rule = _rule("CHAIN-1", activation=ActivationSelector(actions=["audit"]),
                 guard_ids=["GUARD-CONTROLLER-BASH"])
    decision = decide_action_with_rules(
        [rule], {"tool_name": "Read", "tool_input": {"file_path": "README.md"}},
        {"action": "audit"})
    assert "CHAIN-1" in decision.rule_ids
    assert decision.selection_evidence.startswith("sel-")
    result = commit_action_result(tmp_path, decision)
    assert result.status == "success"
    events = load_activity(tmp_path).events
    gate = next(e for e in events if e.event_type == "gate_evaluated")
    assert "CHAIN-1" in (gate.rule_ids or [])
    assert gate.detail.get("selection_evidence") == decision.selection_evidence
    # 证据可复算：同输入同规则得同一标识
    decision2 = decide_action_with_rules(
        [rule], {"tool_name": "Read", "tool_input": {"file_path": "README.md"}},
        {"action": "audit"})
    assert decision2.selection_evidence == decision.selection_evidence


def test_evidence_stable_and_context_sensitive():
    rules = [_rule("A", activation=ActivationSelector(actions=["x"]))]
    s1 = select_rules_for_action(rules, {"action": "x"})
    s2 = select_rules_for_action(rules, {"action": "x"})
    assert s1.evidence_id == s2.evidence_id
    s3 = select_rules_for_action(rules, {"action": "x"}, rules_digest="r2")
    assert s3.evidence_id != s1.evidence_id


def test_b2_audit_rule_selection_to_control_result_chain(tmp_path):
    """B2 贯穿：独立审计动态 SOP（host_check）被选中 → 宿主检查证明进入
    control_result（必需检查+轮次）→ 通过后决策携带同一规则链。"""
    from sopcontrol.control_profile import freeze_profile, normalize_profile, save_draft
    from sopcontrol.control_result import ControlResult, evaluate_control_result

    profile = normalize_profile({
        "profile_id": "audit-q", "scope": {"task": "T-AUD"},
        "checks": {"required": ["jd_fit"], "excluded": []},
        "baseline": {"source_ref": "jd", "generation_mode": "authoritative"},
        "repair": {"max_rounds": 1}, "budget": {"max_audit_calls": 2,
                                                "max_repair_calls": 1}})
    save_draft(tmp_path, profile)
    frozen = freeze_profile(tmp_path, "audit-q")
    rule = _rule("AUDIT-1", activation=ActivationSelector(actions=["audit"]),
                 consumer_markers=["audit-checker"])
    sel = select_rules_for_action([rule], {"action": "audit"})
    assert sel.selected[0].effect == "host_check"
    # 宿主携带检查证明 → control_result 通过
    from datetime import datetime, timezone

    res = ControlResult.model_validate({
        "result_id": "audit-r1", "task_id": "T-AUD", "profile_id": "audit-q",
        "profile_revision": 1, "effective_plan_digest": frozen.digest,
        "input_digest": "in-1", "baseline_digest": "jd-1",
        "checked_dimensions": ["jd_fit"], "check_id": "jd_fit",
        "findings": [], "rounds_used": 0,
        "producer": {"actor": "host-checker", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat()})
    ev = evaluate_control_result(tmp_path, res, frozen)
    assert ev.outcome == "pass"
    # 同一规则进决策链
    decision = decide_action_with_rules(
        [rule], {"tool_name": "Bash", "tool_input": {"command": "audit --jd"}},
        {"action": "audit"})
    assert "AUDIT-1" in decision.rule_ids
    # 缺检查 → control_result 不通过（not_run），决策链不受影响
    res2 = res.model_copy(update={"result_id": "audit-r2",
                                  "checked_dimensions": [],
                                  "input_digest": "in-2"})
    assert evaluate_control_result(tmp_path, res2, frozen).outcome == "not_run"

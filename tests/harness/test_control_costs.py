"""动态规则 P1b：§12.4 成本测试 + 阶段授权。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sopcontrol.cli import main
from sopcontrol.control_profile import freeze_profile, normalize_profile, save_draft
from sopcontrol.control_result import (
    ControlResult,
    control_costs,
    evaluate_control_result,
)
from sopcontrol.tickets import (
    TicketError,
    issue_phase_grant,
    phase_grant_fingerprint,
    redeem_ticket,
)

BASE = {
    "profile_id": "run-cost",
    "scope": {"project": "current-project", "task": "TASK-C", "phase": "audit"},
    "checks": {"required": ["jd_fit"], "excluded": []},
    "baseline": {"source_ref": "jd", "generation_mode": "authoritative"},
    "repair": {"max_rounds": 1},
    "budget": {"max_audit_calls": 5, "max_repair_calls": 2},
}


def _frozen(tmp_path):
    save_draft(tmp_path, normalize_profile(BASE))
    return freeze_profile(tmp_path, "run-cost")


def _result(frozen, rid, **kw):
    base = {
        "result_id": rid, "task_id": "TASK-C", "phase": "audit", "check_id": "jd_fit", "profile_id": "run-cost",
        "profile_revision": 1, "effective_plan_digest": frozen.digest,
        "input_digest": "same-in", "baseline_digest": "same-base",
        "checked_dimensions": ["jd_fit"], "findings": [], "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(kw)
    return ControlResult.model_validate(base)


def test_repeat_same_input_no_duplicate_audit(tmp_path):
    frozen = _frozen(tmp_path)
    first = evaluate_control_result(tmp_path, _result(frozen, "w1"), frozen)
    second = evaluate_control_result(tmp_path, _result(frozen, "w2"), frozen)
    assert (first.outcome, second.outcome) == ("pass", "pass")
    assert any("复用" in r for r in second.reasons)
    costs = control_costs(tmp_path)
    assert costs["audits"] == 1 and costs["reuses"] == 1


def test_no_infinite_repair_rounds(tmp_path):
    frozen = _frozen(tmp_path)
    over = _result(frozen, "w-over", rounds_used=99)
    assert evaluate_control_result(tmp_path, over, frozen).outcome == "block"


def test_phase_grant_not_degraded_and_not_cross_phase(tmp_path):
    g = issue_phase_grant(tmp_path, phase="audit", task_id="TASK-C",
                          allowed_side_effects=["network_request", "run_subprocess"],
                          effective_plan_digest="plan-p")
    fp = phase_grant_fingerprint(phase="audit",
                                 allowed_side_effects=["network_request", "run_subprocess"],
                                 task_id="TASK-C")
    ok = redeem_ticket(tmp_path, ticket_id=g.ticket_id, secret=g.secret,
                       action="phase:audit", input_fingerprint=fp,
                       side_effect="network_request",
                       expected_plan_digest="plan-p", expected_phase="audit")
    assert ok.consumed_at is not None
    g2 = issue_phase_grant(tmp_path, phase="audit", task_id="TASK-C",
                           allowed_side_effects=["network_request"])
    with pytest.raises(TicketError):
        redeem_ticket(tmp_path, ticket_id=g2.ticket_id, secret=g2.secret,
                      action="phase:audit", input_fingerprint=phase_grant_fingerprint(
                          phase="audit", allowed_side_effects=["network_request"],
                          task_id="TASK-C"),
                      side_effect="network_request", expected_phase="other-phase")
    with pytest.raises(TicketError):
        issue_phase_grant(tmp_path, phase="  ", allowed_side_effects=["x"])


def test_profile_change_rechecks_only_affected(tmp_path):
    from sopcontrol.control_lifecycle import recheck_required

    frozen = _frozen(tmp_path)
    assert recheck_required(frozen.profile, ["unrelated_dim"]) == []
    assert recheck_required(frozen.profile, ["jd_fit"]) == ["jd_fit"]


def test_costs_cli_and_conflict_accounting(tmp_path, capsys):
    frozen = _frozen(tmp_path)
    evaluate_control_result(tmp_path, _result(frozen, "k1", findings=[
        {"dimension": "jd_fit", "severity": "tolerated", "summary": "t"}]), frozen)
    evaluate_control_result(tmp_path, _result(frozen, "k2", input_digest="other",
                                              findings=[
        {"dimension": "jd_fit", "severity": "blocking", "summary": "b"}]), frozen)
    assert main(["control-result", "costs", "--path", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "审计 2 次" in out and "容忍偏差 1" in out
    costs = control_costs(tmp_path)
    assert costs["outcomes"].get("block") == 1

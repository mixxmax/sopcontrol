"""动态规则 P0b：§12.2 行为测试 + §12.3 反事实测试。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from sopcontrol.cli import main
from sopcontrol.control_profile import freeze_profile, normalize_profile, save_draft
from sopcontrol.control_result import (
    ControlResult,
    evaluate_control_result,
    idempotency_key,
)

BASE_PROFILE = {
    "profile_id": "run-q",
    "scope": {"project": "current-project", "task": "TASK-9", "phase": "audit"},
    "checks": {"required": ["jd_fit", "factual_accuracy"],
               "excluded": ["style_polish"],
               "modes": {"jd_fit": "block", "factual_accuracy": "block",
                         "style_polish": "ignore"}},
    "baseline": {"source_ref": "jd-snapshot", "generation_mode": "authoritative"},
    "repair": {"max_rounds": 1},
    "budget": {"max_audit_calls": 2, "max_repair_calls": 1},
}


def _frozen(tmp_path):
    save_draft(tmp_path, normalize_profile(BASE_PROFILE))
    return freeze_profile(tmp_path, "run-q")


def _result(**kw):
    base = {
        "result_id": "res-1",
        "task_id": "TASK-9",
        "profile_id": "run-q",
        "profile_revision": 1,
        "effective_plan_digest": "",
        "input_digest": "in-1",
        "baseline_digest": "base-1",
        "checked_dimensions": ["jd_fit", "factual_accuracy"],
        "findings": [],
        "rounds_used": 0,
        "producer": {"actor": "agent-a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(kw)
    return ControlResult.model_validate(base)


def _with_digest(tmp_path, **kw):
    frozen = _frozen(tmp_path)
    kw.setdefault("effective_plan_digest", frozen.digest)
    return frozen, _result(**kw)


# §12.2
def test_single_check_no_scope_expansion(tmp_path):
    frozen, res = _with_digest(tmp_path)
    ev = evaluate_control_result(tmp_path, res, frozen)
    assert ev.outcome == "pass"


def test_excluded_finding_does_not_block(tmp_path):
    frozen, res = _with_digest(tmp_path, findings=[
        {"dimension": "style_polish", "severity": "advisory", "summary": "措辞建议"}])
    ev = evaluate_control_result(tmp_path, res, frozen)
    assert ev.outcome == "pass_with_warnings"


def test_authoritative_baseline_not_auto_upgraded(tmp_path):
    frozen, res = _with_digest(tmp_path)
    assert frozen.profile.baseline.generation_mode == "authoritative"
    assert evaluate_control_result(tmp_path, res, frozen).outcome == "pass"


def test_warn_never_becomes_block(tmp_path):
    frozen, res = _with_digest(tmp_path, findings=[
        {"dimension": "jd_fit", "severity": "tolerated", "summary": "合理夸张保留"}])
    ev = evaluate_control_result(tmp_path, res, frozen)
    assert ev.outcome == "pass_with_warnings"
    assert res.repair_action == "none"


def test_not_run_cannot_satisfy_required(tmp_path):
    frozen, res = _with_digest(tmp_path, checked_dimensions=["jd_fit"])
    assert evaluate_control_result(tmp_path, res, frozen).outcome == "not_run"


def test_tolerated_variance_triggers_no_repair(tmp_path):
    frozen, res = _with_digest(tmp_path, findings=[
        {"dimension": "factual_accuracy", "severity": "tolerated", "summary": "措辞漂移"}])
    ev = evaluate_control_result(tmp_path, res, frozen)
    assert ev.outcome == "pass_with_warnings"


def test_rounds_over_budget_blocks(tmp_path):
    frozen, res = _with_digest(tmp_path, rounds_used=2)
    assert evaluate_control_result(tmp_path, res, frozen).outcome == "block"


def test_same_input_policy_one_key_and_replay_rejected(tmp_path):
    frozen = _frozen(tmp_path)
    r1 = _result(result_id="res-a", effective_plan_digest=frozen.digest)
    r2 = _result(result_id="res-b", effective_plan_digest=frozen.digest)
    assert idempotency_key(r1) == idempotency_key(r2)
    assert evaluate_control_result(tmp_path, r1, frozen).outcome == "pass"
    assert evaluate_control_result(tmp_path, r2, frozen).outcome == "pass"
    # 同一 result_id 重放 → 拒绝
    assert evaluate_control_result(tmp_path, r1, frozen).outcome == "unknown"


def test_revision_change_invalidates_old_result(tmp_path):
    save_draft(tmp_path, normalize_profile(BASE_PROFILE))
    f1 = freeze_profile(tmp_path, "run-q")
    f2 = freeze_profile(tmp_path, "run-q")
    assert f2.revision == 2
    res = _result(result_id="res-old", effective_plan_digest=f1.digest, profile_revision=1)
    assert evaluate_control_result(tmp_path, res, f2).outcome == "unknown"


def test_actor_change_does_not_relax_plan(tmp_path):
    save_draft(tmp_path, normalize_profile({**BASE_PROFILE, "baseline": {
        "source_ref": "jd", "generation_mode": "authoritative",
        "independence_required": "separate_actor"}}))
    frozen = freeze_profile(tmp_path, "run-q")
    weak = _result(result_id="res-w", effective_plan_digest=frozen.digest,
                   producer={"actor": "agent-b", "independence": "self_check"})
    assert evaluate_control_result(tmp_path, weak, frozen).outcome == "unknown"
    strong = _result(result_id="res-s", effective_plan_digest=frozen.digest,
                     producer={"actor": "agent-c", "independence": "separate_actor"})
    assert evaluate_control_result(tmp_path, strong, frozen).outcome == "pass"


# §12.3 反事实
def test_excluded_disguised_as_required_blocked(tmp_path):
    frozen, res = _with_digest(tmp_path, checked_dimensions=[
        "jd_fit", "factual_accuracy", "style_polish"])
    ev = evaluate_control_result(tmp_path, res, frozen)
    assert ev.outcome == "block"


def test_tampered_digest_rejected(tmp_path):
    frozen, res = _with_digest(tmp_path, effective_plan_digest="plan-deadbeef")
    assert evaluate_control_result(tmp_path, res, frozen).outcome == "unknown"


def test_free_text_instead_of_structured_rejected(tmp_path, capsys):
    frozen = _frozen(tmp_path)
    bad = tmp_path / "free.json"
    bad.write_text(json.dumps({"reason": "看起来不错，通过"}), encoding="utf-8")
    rc = main(["control-result", "evaluate", "--file", str(bad),
               "--profile", "run-q", "--revision", "1", "--path", str(tmp_path)])
    assert rc == 2


def test_cli_rc_mapping(tmp_path, capsys):
    frozen = _frozen(tmp_path)
    assert main(["profile", "accept", "run-q", "--revision", "1", "--task", "TASK-9",
                 "--digest", "base-1", "--path", str(tmp_path)]) == 0
    capsys.readouterr()

    def run(res, name):
        p = tmp_path / f"{name}.json"
        p.write_text(res.model_dump_json(), encoding="utf-8")
        rc = main(["control-result", "evaluate", "--file", str(p),
                   "--profile", "run-q", "--revision", "1", "--path", str(tmp_path)])
        capsys.readouterr()
        return rc

    assert run(_result(result_id="c-pass", effective_plan_digest=frozen.digest), "a") == 0
    assert run(_result(result_id="c-warn", effective_plan_digest=frozen.digest, findings=[
        {"dimension": "jd_fit", "severity": "advisory", "summary": "x"}]), "b") == 0
    assert run(_result(result_id="c-block", effective_plan_digest=frozen.digest, findings=[
        {"dimension": "jd_fit", "severity": "blocking", "summary": "x"}]), "c") == 1
    assert run(_result(result_id="c-notrun", effective_plan_digest=frozen.digest,
                       checked_dimensions=["jd_fit"]), "d") == 2


def test_ticket_plan_digest_binding(tmp_path):
    from sopcontrol.tickets import TicketError, issue_ticket, redeem_ticket

    t = issue_ticket(tmp_path, action="network.scan", input_fingerprint="fp-1",
                     allowed_side_effects=["network_request"],
                     effective_plan_digest="plan-abc")
    assert t.effective_plan_digest == "plan-abc"
    ok = redeem_ticket(tmp_path, ticket_id=t.ticket_id, secret=t.secret,
                       action="network.scan", input_fingerprint="fp-1",
                       side_effect="network_request", expected_plan_digest="plan-abc")
    assert ok.consumed_at is not None

    t2 = issue_ticket(tmp_path, action="network.scan", input_fingerprint="fp-1",
                      allowed_side_effects=["network_request"],
                      effective_plan_digest="plan-abc")
    with pytest.raises(TicketError):
        redeem_ticket(tmp_path, ticket_id=t2.ticket_id, secret=t2.secret,
                      action="network.scan", input_fingerprint="fp-1",
                      side_effect="network_request", expected_plan_digest="plan-other")
    # 未绑定 digest 的旧票行为不变
    t3 = issue_ticket(tmp_path, action="network.scan", input_fingerprint="fp-1",
                      allowed_side_effects=["network_request"])
    assert redeem_ticket(tmp_path, ticket_id=t3.ticket_id, secret=t3.secret,
                         action="network.scan", input_fingerprint="fp-1",
                         side_effect="network_request",
                         expected_plan_digest="plan-abc").consumed_at is not None


def test_contract_binds_profile_fields():
    from sopcontrol.task import Contract

    c = Contract(objective="o", allowed_writes=[], required_rules=[])
    assert (c.control_profile_id, c.control_profile_revision, c.effective_plan_digest) == ("", 0, "")
    c2 = Contract(objective="o", allowed_writes=[], required_rules=[],
                  control_profile_id="run-q", control_profile_revision=2,
                  effective_plan_digest="plan-x")
    assert c2.effective_plan_digest == "plan-x"

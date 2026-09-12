"""T-0094：decide() 纯函数（显式 GateState，无 I/O、无时钟）。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sopcontrol.control_profile import normalize_profile
from sopcontrol.control_result import (
    ControlResult,
    GateState,
    decide_control_result,
    idempotency_key,
)

BASE = {
    "profile_id": "pure",
    "scope": {"project": "current-project", "task": "TASK-P", "phase": "audit"},
    "checks": {"required": ["jd_fit", "factual_accuracy"],
               "excluded": ["style"],
               "modes": {"jd_fit": "block", "factual_accuracy": "report_only"}},
    "baseline": {"source_ref": "jd", "generation_mode": "authoritative",
                 "require_accept": True, "independence_required": "separate_actor"},
    "tolerance": {"reasonable_exaggeration": "allowed"},
    "repair": {"max_rounds": 1},
    "budget": {"max_audit_calls": 2, "max_repair_calls": 1},
}


def _frozen():
    from sopcontrol.control_profile import plan_digest

    p = normalize_profile(BASE)
    digest = plan_digest(p, 1)

    class F:
        pass

    f = F()
    f.profile_id, f.revision, f.digest, f.profile = "pure", 1, digest, p
    return f


def _result(**kw):
    base = {
        "result_id": "pure-1", "task_id": "TASK-P", "profile_id": "pure",
        "profile_revision": 1, "effective_plan_digest": "",
        "input_digest": "in", "baseline_digest": "base",
        "checked_dimensions": ["jd_fit", "factual_accuracy"],
        "findings": [], "rounds_used": 0,
        "producer": {"actor": "agent-b", "independence": "separate_actor"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(kw)
    return ControlResult.model_validate(base)


def _state(**kw):
    base = {"consumed_ids": set(), "cached": None,
            "accept_digest": "base", "accept_mode": "authoritative",
            "accept_missing": False, "task_identity": "agent-exec",
            "evidence_ids": set(), "audits_used": 0, "repair_rounds_used": 0,
            "now_iso": datetime.now(timezone.utc).isoformat()}
    base.update(kw)
    return GateState.model_validate(base)


def _ok_result(frozen, **kw):
    kw.setdefault("effective_plan_digest", frozen.digest)
    return _result(**kw)


def test_pure_deterministic_and_next_action():
    frozen = _frozen()
    res = _ok_result(frozen)
    e1 = decide_control_result(res, frozen, _state())
    e2 = decide_control_result(res, frozen, _state())
    assert e1 == e2 and e1.outcome == "pass"
    assert e1.next_action  # 每个判定带下一步


def test_report_only_mode_downgrades_blocking():
    frozen = _frozen()
    res = _ok_result(frozen, result_id="m1", findings=[
        {"dimension": "factual_accuracy", "severity": "blocking", "summary": "x"}])
    ev = decide_control_result(res, frozen, _state())
    assert ev.outcome == "pass_with_warnings"
    assert any("report_only" in r for r in ev.reasons)


def test_tolerance_allowed_caps_blocking():
    frozen = _frozen()
    res = _ok_result(frozen, result_id="m2", findings=[
        {"dimension": "jd_fit", "severity": "blocking", "summary": "夸张",
         "category": "reasonable_exaggeration"}])
    ev = decide_control_result(res, frozen, _state())
    assert ev.outcome == "pass_with_warnings"


def test_budgets_have_teeth():
    frozen = _frozen()
    res = _ok_result(frozen, result_id="b1")
    assert decide_control_result(res, frozen, _state(audits_used=2)).outcome == "block"
    assert decide_control_result(res, frozen, _state(repair_rounds_used=2)).outcome == "block"


def test_independence_proofs():
    frozen = _frozen()
    anon = _ok_result(frozen, result_id="i1",
                      producer={"actor": "", "independence": "separate_actor"})
    assert decide_control_result(anon, frozen, _state()).outcome == "unknown"
    self_claim = _ok_result(frozen, result_id="i2",
                            producer={"actor": "agent-exec",
                                      "independence": "separate_actor"})
    assert decide_control_result(self_claim, frozen, _state()).outcome == "unknown"
    noctx = _ok_result(frozen, result_id="i3",
                       producer={"actor": "agent-b", "independence": "separate_context"})
    assert decide_control_result(noctx, frozen, _state()).outcome == "unknown"
    human = _ok_result(frozen, result_id="i4",
                       producer={"actor": "human-z", "independence": "human_required",
                                 "evidence_ref": "ev-missing"})
    assert decide_control_result(human, frozen, _state()).outcome == "unknown"
    human_ok = _ok_result(frozen, result_id="i5",
                          producer={"actor": "human-z", "independence": "human_required",
                                    "evidence_ref": "ev-1"})
    assert decide_control_result(human_ok, frozen,
                                 _state(evidence_ids={"ev-1"})).outcome == "pass"


def test_baseline_accept_in_library_no_bypass():
    frozen = _frozen()
    res = _ok_result(frozen, result_id="a1")
    assert decide_control_result(res, frozen, _state(accept_missing=True)).outcome == "unknown"
    changed = _ok_result(frozen, result_id="a2", baseline_digest="other")
    assert decide_control_result(changed, frozen, _state()).outcome == "unknown"
    escalated = _ok_result(frozen, result_id="a3", baseline_mode="verify")
    assert decide_control_result(escalated, frozen, _state()).outcome == "unknown"


def test_binding_mismatch_rejected():
    frozen = _frozen()
    res = _ok_result(frozen, result_id="t1")
    st = _state(binding_profile="pure", binding_revision=1,
                binding_digest="plan-OTHER")
    assert decide_control_result(res, frozen, st).outcome == "unknown"
    st_ok = _state(binding_profile="pure", binding_revision=1,
                   binding_digest=frozen.digest)
    assert decide_control_result(res, frozen, st_ok).outcome == "pass"


def test_all_outcomes_carry_next_action():
    frozen = _frozen()
    cases = [
        _ok_result(frozen, result_id="n1"),
        _ok_result(frozen, result_id="n2", checked_dimensions=["jd_fit"]),
        _ok_result(frozen, result_id="n3", effective_plan_digest="plan-x"),
    ]
    for res in cases:
        ev = decide_control_result(res, frozen, _state())
        assert ev.next_action, ev.outcome


def test_compose_tighten_only_and_deterministic():
    from sopcontrol.control_profile import (
        ProfileError,
        compose_effective_plan,
        normalize_profile,
    )

    base = normalize_profile({**BASE, "profile_id": "pure",
                              "checks": {"required": ["jd_fit"],
                                         "excluded": ["style"]}})
    task = normalize_profile(BASE)
    plain = compose_effective_plan(_frozen_like(task), None)
    assert plain.digest
    run = {"exclude_add": ["extra"], "mode_tighten": {"jd_fit": "block"},
           "budget_cap": {"max_audit_calls": 1}, "repair_max_rounds": 1,
           "tolerance_tighten": {}}
    composed = compose_effective_plan(_frozen_like(task), run,
                                      base_profile=base)
    assert composed.digest != plain.digest
    assert "extra" in composed.profile.checks.excluded
    twin = compose_effective_plan(_frozen_like(task), dict(run),
                                  base_profile=base)
    assert twin.digest == composed.digest
    with pytest.raises(ProfileError):
        compose_effective_plan(_frozen_like(task), {"mode_tighten": {"jd_fit": "required"}})
    with pytest.raises(ProfileError):
        compose_effective_plan(_frozen_like(task), {"exclude_add": ["jd_fit"]})
    with pytest.raises(ProfileError):
        compose_effective_plan(_frozen_like(task), {"budget_cap": {"max_audit_calls": 99}})
    with pytest.raises(ProfileError):
        compose_effective_plan(_frozen_like(task), {"unknown_key": 1})


def _frozen_like(profile):
    from sopcontrol.control_profile import plan_digest

    class F:
        pass

    f = F()
    f.profile_id, f.revision = profile.profile_id, 1
    f.digest = plan_digest(profile, 1)
    f.profile = profile
    return f


def test_run_override_evaluate_binds_composed_digest(tmp_path):
    from sopcontrol.control_lifecycle import accept_baseline
    from sopcontrol.control_profile import compose_effective_plan
    from sopcontrol.control_result import evaluate_control_result
    from sopcontrol.task import Contract, TaskRecord, TaskStore

    frozen = _frozen()
    run = {"exclude_add": ["extra"]}
    composed = compose_effective_plan(frozen, run)
    accept_baseline(tmp_path, task_id="TASK-P", profile_id="pure", revision=1,
                    source_ref="jd", baseline_digest="base",
                    baseline_mode="authoritative")
    (tmp_path / ".sopcontrol" / "tasks").mkdir(parents=True, exist_ok=True)
    TaskStore(tmp_path).save(TaskRecord(
        task_id="TASK-P",
        contract=Contract(objective="o", allowed_writes=[], required_rules=[],
                          model_identity="exec-1")))
    res = _ok_result(frozen, result_id="o1",
                     effective_plan_digest=composed.digest)
    ev = evaluate_control_result(tmp_path, res, frozen, run_override=dict(run),
                                 task_id="TASK-P")
    assert ev.outcome == "pass"
    stale = _ok_result(frozen, result_id="o2",
                       effective_plan_digest=frozen.digest)
    assert evaluate_control_result(tmp_path, stale, frozen,
                                   run_override=dict(run),
                                   task_id="TASK-P").outcome == "unknown"


def test_identifier_traversal_rejected(tmp_path):
    from sopcontrol.control_lifecycle import accept_baseline
    from sopcontrol.control_profile import ProfileError, freeze_profile, save_draft

    import pytest

    evil = normalize_profile({**BASE, "profile_id": "../../escaped"})
    with pytest.raises(ValueError):
        save_draft(tmp_path, evil)
    with pytest.raises(ValueError):
        freeze_profile(tmp_path, "../../escaped")
    with pytest.raises(ValueError):
        accept_baseline(tmp_path, task_id="../../escaped", profile_id="pure",
                        revision=1, source_ref="s", baseline_digest="b",
                        baseline_mode="authoritative")
    assert not (tmp_path / "escaped").exists()
    assert not (tmp_path.parent / "escaped").exists()

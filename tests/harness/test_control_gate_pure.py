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
        "result_id": "pure-1", "task_id": "TASK-P", "phase": "audit", "check_id": "jd_fit", "profile_id": "pure",
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
    # 修正预算只在真需要修正（blocking）时咬合；干净结果不受影响
    assert decide_control_result(res, frozen, _state(repair_rounds_used=2)).outcome == "pass"
    blocking = _ok_result(frozen, result_id="b2", findings=[
        {"dimension": "jd_fit", "severity": "blocking", "summary": "x"}])
    assert decide_control_result(blocking, frozen,
                                 _state(repair_rounds_used=2)).outcome == "block"


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
    from sopcontrol.capability import actor_snapshot

    snap = actor_snapshot(None, current_model="exec-1")
    composed = compose_effective_plan(frozen, run, actor_snapshot=dict(snap))
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


def test_expired_profile_judged_at_decision_time():
    from datetime import timedelta

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    expired = normalize_profile({**BASE, "expires_at": past})
    valid = normalize_profile({**BASE, "expires_at": future})
    frozen_exp = _frozen_like(expired)
    frozen_ok = _frozen_like(valid)
    res = _ok_result(frozen_exp)
    assert decide_control_result(res, frozen_exp, _state()).outcome == "unknown"
    res2 = _ok_result(frozen_ok)
    assert decide_control_result(res2, frozen_ok, _state()).outcome == "pass"


def test_time_fail_closed_matrix():
    frozen = _frozen()
    # now 缺失 + 有过期时间 → unknown（不能证明未过期）
    res = _ok_result(frozen)
    st = _state()
    st.now_iso = ""
    object.__setattr__(frozen, "profile", normalize_profile(
        {**BASE, "expires_at": (datetime.now(timezone.utc)).isoformat()}))
    assert decide_control_result(res, frozen, st).outcome == "unknown"
    # now 等于过期时刻 → 已过期
    exp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    frozen2_profile = normalize_profile({**BASE, "expires_at": exp})
    frozen2 = _frozen_like(frozen2_profile)
    res2 = _ok_result(frozen2)
    st2 = _state()
    st2.now_iso = exp
    assert decide_control_result(res2, frozen2, st2).outcome == "unknown"
    # 非法 expires 手工构造 → unknown（normalize 之外的防御）
    bad = frozen2_profile.model_copy(update={"expires_at": "yesterday-ish"})
    frozen3 = _frozen_like(bad)
    res3 = _ok_result(frozen3)
    assert decide_control_result(res3, frozen3, _state()).outcome == "unknown"


def test_stop_when_max_rounds_in_gate():
    profile = normalize_profile({**BASE, "stop_when": ["pass", "max_rounds"]})
    frozen = _frozen_like(profile)
    res = _ok_result(frozen, result_id="s1", rounds_used=2)
    ev = decide_control_result(res, frozen, _state())
    assert ev.outcome == "block" and "停止条件" in ev.reasons[0]


def test_round_boundary_matrix():
    # round 0 / max 0 + blocking → 直接 block（无修正额度）
    p0 = normalize_profile({**BASE, "repair": {"max_rounds": 0}})
    f0 = _frozen_like(p0)
    r0 = _ok_result(f0, result_id="b0", findings=[
        {"dimension": "jd_fit", "severity": "blocking", "summary": "x"}])
    assert decide_control_result(r0, f0, _state()).outcome == "block"
    # round=max-1 + blocking → block 但给修复指引（还可修一次）
    p1 = normalize_profile(BASE)
    f1 = _frozen_like(p1)
    r1 = _ok_result(f1, result_id="b1", rounds_used=0, findings=[
        {"dimension": "jd_fit", "severity": "blocking", "summary": "x"}])
    ev1 = decide_control_result(r1, f1, _state())
    assert ev1.outcome == "block" and "修正后重跑" in ev1.next_action
    # round=max + blocking → 终止（本轮 max_rounds=1，已用 1 轮）
    r2 = _ok_result(f1, result_id="b2", rounds_used=1, findings=[
        {"dimension": "jd_fit", "severity": "blocking", "summary": "x"}])
    ev2 = decide_control_result(r2, f1, _state())
    assert ev2.outcome == "block" and "无修正额度" in ev2.reasons[0]
    # round=max+1 → 越界损坏态 block
    r3 = _ok_result(f1, result_id="b3", rounds_used=2)
    ev3 = decide_control_result(r3, f1, _state())
    assert ev3.outcome == "block" and "越界" in ev3.reasons[0]
    # 干净结果不受轮数门影响（修好了就通过）
    r4 = _ok_result(f0, result_id="b4")
    assert decide_control_result(r4, f0, _state()).outcome == "pass"


def test_compose_merges_all_layers_tighten_only():
    from sopcontrol.control_profile import ProfileError, compose_effective_plan

    base = normalize_profile({
        **BASE, "checks": {"required": ["jd_fit", "factual_accuracy", "llmo"],
                           "excluded": [],
                           "modes": {"jd_fit": "block", "llmo": "required"}},
        "tolerance": {"reasonable_exaggeration": "report_only"},
        "budget": {"max_audit_calls": 5, "max_repair_calls": 2},
        "repair": {"max_rounds": 2},
        "stop_when": ["pass"],
    })
    task = normalize_profile({
        **BASE,
        "tolerance": {"reasonable_exaggeration": "report_only"},
        "checks": {"required": ["jd_fit", "factual_accuracy"],
                   "excluded": [],
                   "modes": {"jd_fit": "block", "factual_accuracy": "block"}},
    })
    composed = compose_effective_plan(_frozen_like(task), None, base_profile=base)
    assert set(composed.profile.checks.required) == {"jd_fit", "factual_accuracy", "llmo"}
    assert composed.profile.checks.modes["jd_fit"] == "block"
    assert composed.profile.tolerance["reasonable_exaggeration"] == "report_only"
    assert composed.profile.budget.max_audit_calls == 2
    assert composed.profile.repair.max_rounds == 1
    assert composed.layers["base"]["profile"] == "pure"
    # 放宽任一层即拒绝
    loose = dict(BASE)
    loose["budget"] = {"max_audit_calls": 99, "max_repair_calls": 1}
    with pytest.raises(ProfileError):
        compose_effective_plan(_frozen_like(normalize_profile(loose)), None,
                               base_profile=base)

"""最终闭环包 A：有效计划收口反例优先（§15.1/§7.4）。

每个测试注明：初始配置 / 调用入口 / 预期 / 为什么不能 pass / 用了哪个 digest。
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sopcontrol.control_profile import (
    ProfileError,
    compile_effective_profile,
    compose_effective_plan,
    extract_task_digest,
    normalize_profile,
    plan_digest,
)

BASE = {
    "profile_id": "eff",
    "scope": {"project": "current-project", "task": "TASK-E", "phase": "audit"},
    "checks": {"required": ["check-a"], "excluded": []},
    "baseline": {"source_ref": "jd", "generation_mode": "authoritative"},
    "repair": {"max_rounds": 1},
    "budget": {"max_audit_calls": 2, "max_repair_calls": 1},
}


def _frozen_like(profile, rev=1):
    class F:
        pass

    f = F()
    f.profile_id, f.revision = profile.profile_id, rev
    f.digest = plan_digest(profile, rev)
    f.profile = profile
    return f


def test_required_defaults_to_block_and_cannot_be_weakened():
    # base.required 含 check-a 且无 modes；task 设 report_only → 拒绝（隐含 block 被弱化）
    base = normalize_profile(BASE)
    assert base.checks.modes["check-a"] == "block"  # 物化不断言只看不见
    task = normalize_profile({**BASE, "checks": {
        "required": ["check-a"], "excluded": [], "modes": {"check-a": "report_only"}}})
    with pytest.raises(ProfileError):
        compose_effective_plan(_frozen_like(task), None, base_profile=base)


def test_explicit_block_uphold_and_advisory_rejected():
    base = normalize_profile(BASE)
    same = normalize_profile({**BASE, "checks": {
        "required": ["check-a"], "excluded": [], "modes": {"check-a": "block"}}})
    composed = compose_effective_plan(_frozen_like(same), None, base_profile=base)
    assert composed.profile.checks.modes["check-a"] == "block"
    with pytest.raises(ProfileError):
        normalize_profile({**BASE, "checks": {
            "required": ["check-a"], "excluded": [],
            "modes": {"check-a": "advisory"}}})  # 非法枚举：schema 即拒


def test_required_excluded_conflict_and_scope_expansion_rejected():
    with pytest.raises(ProfileError):
        normalize_profile({**BASE, "checks": {
            "required": ["check-a"], "excluded": ["check-a"]}})
    base = normalize_profile({**BASE, "scope": {
        "project": "proj-1", "task": "TASK-E", "phase": "audit"}})
    wider = normalize_profile({**BASE, "scope": {
        "project": "proj-2", "task": "TASK-E", "phase": "audit"}})
    with pytest.raises(ProfileError):
        compose_effective_plan(_frozen_like(wider), None, base_profile=base)


def test_unknown_fields_rejected():
    bad = dict(BASE)
    bad["mystery_layer"] = {"strict": True}
    with pytest.raises(ProfileError):
        normalize_profile(bad)


def test_repair_budget_fields_merged_and_growth_rejected():
    base = normalize_profile(BASE)
    with pytest.raises(ProfileError):
        normalize_profile({**BASE, "budget": {"max_audit_calls": 99,
                                              "max_repair_calls": 1},
                           "checks": {"required": ["check-a"], "excluded": []},
                           })
    # 组合取最小（只收紧）
    small = normalize_profile({**BASE, "budget": {"max_audit_calls": 1,
                                                  "max_repair_calls": 1},
                               "repair": {"max_rounds": 0}})
    composed = compose_effective_plan(_frozen_like(small), None, base_profile=base)
    assert composed.profile.budget.max_audit_calls == 1
    assert composed.profile.repair.max_rounds == 0
    assert set(composed.profile.stop_when) >= {"pass"}


def test_stop_when_omitted_inherits_and_explicit_reduction_rejected():
    # §9.5 第一行：base 非默认 + task 省略 stop_when → 继承（不得误判放宽）
    base = normalize_profile({**BASE, "stop_when": ["pass", "max_rounds"]})
    omitted = normalize_profile(BASE)  # 未声明 stop_when
    composed = compose_effective_plan(_frozen_like(omitted), None, base_profile=base)
    assert set(composed.profile.stop_when) == {"pass", "max_rounds"}
    # 显式声明更少停止条件 = 显式放宽 → 拒绝
    fewer = normalize_profile({**BASE, "stop_when": ["pass"]})
    with pytest.raises(ProfileError):
        compose_effective_plan(_frozen_like(fewer), None, base_profile=base)


def test_expires_normalized_rejected_and_earliest_wins():
    with pytest.raises(ProfileError):
        normalize_profile({**BASE, "expires_at": "not-a-date"})
    with pytest.raises(ProfileError):
        normalize_profile({**BASE, "expires_at": "2026-09-12T10:00:00"})  # 无时区
    a = normalize_profile({**BASE, "expires_at": "2026-09-12T10:00:00+08:00"})
    b = normalize_profile({**BASE, "expires_at": "2026-09-12T02:00:00Z"})
    assert a.expires_at == b.expires_at  # 同一时刻统一 UTC
    assert a.expires_at.endswith("+00:00")
    early = normalize_profile({**BASE, "expires_at": "2026-09-11T02:00:00Z"})
    late = normalize_profile({**BASE, "expires_at": "2026-09-13T02:00:00Z"})
    composed = compose_effective_plan(_frozen_like(late), None,
                                      base_profile=early)
    assert composed.profile.expires_at == early.expires_at


def test_four_layers_in_digest_and_stable():
    from sopcontrol.control_profile import compose_effective_plan as _c

    base = normalize_profile(BASE)
    task = normalize_profile(BASE)
    run = {"exclude_add": ["extra"]}
    actor = {"tier": "weak", "max_repairs": 1, "write_granularity": "file",
             "strict_schema": True, "source": "fixture", "evaluation_id": "ev-1",
             "approved": True, "approved_by": "user"}
    c1 = _c(_frozen_like(task), dict(run), base_profile=base, actor_snapshot=dict(actor))
    c2 = _c(_frozen_like(task), dict(run), base_profile=base, actor_snapshot=dict(actor))
    assert c1.digest == c2.digest
    for key in ("base", "task", "run", "actor"):
        assert key in c1.layers, c1.layers
    changed = dict(run)
    changed["exclude_add"] = ["other"]
    assert _c(_frozen_like(task), changed, base_profile=base,
              actor_snapshot=dict(actor)).digest != c1.digest
    naked = _c(_frozen_like(task), None)
    assert naked.digest == plan_digest(task, 1)  # 无层时 digest 保持稳定


def test_actor_unapproved_goes_conservative():
    from sopcontrol.capability import actor_snapshot

    snap = actor_snapshot(None, current_model="someone")
    assert snap["approved"] is False and snap["tier"] == "unknown"
    assert snap["max_repairs"] == 1
    assert "digest" in snap


def test_merge_preserves_baseline_source_ref():
    base = normalize_profile({**BASE, "baseline": {"source_ref": "golden-baseline-v1", "generation_mode": "authoritative"}})
    task = normalize_profile({**BASE, "baseline": {"source_ref": "", "generation_mode": "authoritative"}})
    composed = compose_effective_plan(_frozen_like(task), None, base_profile=base)
    assert composed.profile.baseline.source_ref == "golden-baseline-v1"


def test_baseline_source_ref_mismatch_is_rejected():
    base = normalize_profile({**BASE, "baseline": {"source_ref": "golden-baseline-v1", "generation_mode": "authoritative"}})
    task = normalize_profile({**BASE, "baseline": {"source_ref": "different-baseline-v2", "generation_mode": "authoritative"}})
    with pytest.raises(ProfileError, match="baseline.source_ref"):
        compose_effective_plan(_frozen_like(task), None, base_profile=base)


def test_recheck_unchanged_input_omitted_inherits_and_explicit_weaken_rejected():
    # §9.5：task 省略 recheck_unchanged_input → 继承 base 的 True
    base = normalize_profile({**BASE, "repair": {"max_rounds": 1, "recheck_unchanged_input": True}})
    omitted = normalize_profile({**BASE, "repair": {"max_rounds": 1}})
    composed = compose_effective_plan(_frozen_like(omitted), None, base_profile=base)
    assert composed.profile.repair.recheck_unchanged_input is True
    # 显式写出更宽松的 False → 必须拒绝（不是静默收紧，§9.3）
    task = normalize_profile({**BASE, "repair": {"max_rounds": 1, "recheck_unchanged_input": False}})
    with pytest.raises(ProfileError):
        compose_effective_plan(_frozen_like(task), None, base_profile=base)


def test_stop_after_pass_omitted_inherits_and_explicit_weaken_rejected():
    # §9.5：task 省略 stop_after_pass → 继承 base 的 True
    base = normalize_profile({**BASE, "repair": {"max_rounds": 1, "stop_after_pass": True}})
    omitted = normalize_profile({**BASE, "repair": {"max_rounds": 1}})
    composed = compose_effective_plan(_frozen_like(omitted), None, base_profile=base)
    assert composed.profile.repair.stop_after_pass is True
    # 显式写出更宽松的 False → 必须拒绝（§9.3）
    task = normalize_profile({**BASE, "repair": {"max_rounds": 1, "stop_after_pass": False}})
    with pytest.raises(ProfileError):
        compose_effective_plan(_frozen_like(task), None, base_profile=base)


def test_current_project_cannot_widen_narrow_scope():
    base = normalize_profile({**BASE, "scope": {"project": "payment-service", "task": "TASK-E", "phase": "audit"}})
    task = normalize_profile({**BASE, "scope": {"project": "current-project", "task": "TASK-E", "phase": "audit"}})
    with pytest.raises(ProfileError, match="scope"):
        compose_effective_plan(_frozen_like(task), None, base_profile=base)


def test_unknown_actor_fields_are_rejected():
    task = normalize_profile(BASE)
    bad_actor = {
        "tier": "strong",
        "max_repairs": 2,
        "super_admin_bypass": True,
    }
    with pytest.raises(ProfileError, match="actor"):
        compose_effective_plan(_frozen_like(task), None, actor_snapshot=bad_actor)


def test_unapproved_actor_uses_conservative_ceiling():
    task = normalize_profile({**BASE, "repair": {"max_rounds": 3}})
    unapproved_actor = {
        "tier": "strong",
        "max_repairs": 3,
        "approved": False,
        "model": "unapproved-model",
    }
    composed = compose_effective_plan(_frozen_like(task), None, actor_snapshot=unapproved_actor)
    assert composed.profile.repair.max_rounds <= 1
    assert composed.layers["actor"]["tier"] == "unknown"


def test_all_layers_are_present_in_effective_plan_digest():
    base = normalize_profile({**BASE, "budget": {"max_audit_calls": 4, "max_repair_calls": 2}})
    task = normalize_profile({**BASE, "budget": {"max_audit_calls": 2, "max_repair_calls": 1}})
    run = {"exclude_add": ["extra-check"]}
    actor = {"tier": "weak", "max_repairs": 1, "approved": True}
    composed = compose_effective_plan(_frozen_like(task), run, base_profile=base, actor_snapshot=actor)
    assert "base" in composed.layers
    assert "task" in composed.layers
    assert "run" in composed.layers
    assert "actor" in composed.layers
    assert isinstance(composed.layers["task"], dict)
    assert composed.layers["task"].get("digest") == _frozen_like(task).digest

    # 1. Base change
    base2 = normalize_profile({**BASE, "budget": {"max_audit_calls": 3, "max_repair_calls": 2}})
    c_base2 = compose_effective_plan(_frozen_like(task), run, base_profile=base2, actor_snapshot=actor)
    assert c_base2.digest != composed.digest

    # 2. Run change
    run2 = {"exclude_add": ["another-check"]}
    c_run2 = compose_effective_plan(_frozen_like(task), run2, base_profile=base, actor_snapshot=actor)
    assert c_run2.digest != composed.digest

    # 3. Actor change
    actor2 = {"tier": "weak", "max_repairs": 1, "approved": True, "model": "other-model"}
    c_actor2 = compose_effective_plan(_frozen_like(task), run, base_profile=base, actor_snapshot=actor2)
    assert c_actor2.digest != composed.digest


def test_raw_and_frozen_evaluation_have_one_semantics(tmp_path):
    from sopcontrol.control_result import ControlResult, evaluate_control_result
    base = normalize_profile({**BASE, "profile_id": "eval-sem"})
    task = normalize_profile({**BASE, "profile_id": "eval-sem", "repair": {"max_rounds": 1}})
    frozen_task = _frozen_like(task)

    run = {"exclude_add": ["extra"]}
    actor = {"tier": "weak", "max_repairs": 1, "approved": True}

    composed = compose_effective_plan(frozen_task, run, base_profile=base, actor_snapshot=actor)

    res = ControlResult.model_validate({
        "result_id": "res-sem-1",
        "task_id": "TASK-E",
        "phase": "audit",
        "check_id": "check-a",
        "profile_id": "eval-sem",
        "profile_revision": 1,
        "effective_plan_digest": composed.digest,
        "input_digest": "inp-1",
        "baseline_digest": "base-1",
        "checked_dimensions": ["check-a"],
        "findings": [],
        "rounds_used": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    p1 = tmp_path / "run1"
    p1.mkdir()
    p2 = tmp_path / "run2"
    p2.mkdir()
    ev1 = evaluate_control_result(p1, res, composed)

    ev2 = evaluate_control_result(
        p2,
        res.model_copy(update={"result_id": "res-sem-2"}),
        frozen_task,
        run_override=run,
        base_profile=base,
        actor_snapshot=actor,
    )
    assert ev1.outcome == "pass"
    assert ev2.outcome == "pass"
    assert ev1.outcome == ev2.outcome
    assert ev1.idempotency_key != ""
    assert ev2.idempotency_key != ""


def test_extract_task_digest_variations():
    # 1. Custom object without task_digest, with layers dict
    class MockPlan1:
        layers = {"task_digest": "legacy-task-digest-123"}
        digest = "plan-digest-123"

    assert extract_task_digest(MockPlan1()) == "legacy-task-digest-123"

    # 2. Custom object with layers containing task dict with digest
    class MockPlan2:
        layers = {"task": {"digest": "task-dict-digest-456"}}
        digest = "plan-digest-456"

    assert extract_task_digest(MockPlan2()) == "task-dict-digest-456"

    # 3. Custom object without layers
    class MockPlan3:
        digest = "pure-digest-789"

    assert extract_task_digest(MockPlan3()) == "pure-digest-789"

    # 4. Profile with task not a dict
    base = normalize_profile(BASE)
    composed = compose_effective_plan(_frozen_like(base))
    composed.layers["task"] = "string-task"
    composed.layers["task_digest"] = "string-task-digest"
    assert composed.task_digest == "string-task-digest"


def test_compile_effective_profile_tolerance_and_repair_tighten():
    prof = normalize_profile(BASE)

    # 1. run 不得放宽 repair_max_rounds
    with pytest.raises(ProfileError, match="run 不得放宽 repair.max_rounds"):
        compile_effective_profile(prof, run_override={"repair_max_rounds": 99})

    # 2. run 允许收紧 repair_max_rounds
    tightened = compile_effective_profile(prof, run_override={"repair_max_rounds": 0})
    assert tightened.repair.max_rounds == 0

    # 3. tolerance 非法等级
    with pytest.raises(ProfileError, match="run tolerance 非法"):
        compile_effective_profile(prof, run_override={"tolerance_tighten": {"leak": "invalid_level"}})

    # 4. run 不得放宽 tolerance (假设当前已是 block)
    prof_strict = normalize_profile({**BASE, "tolerance": {"leak": "block"}})
    with pytest.raises(ProfileError, match="run 不得放宽 tolerance"):
        compile_effective_profile(prof_strict, run_override={"tolerance_tighten": {"leak": "allowed"}})

    # 5. run 允许收紧 tolerance
    tightened_tol = compile_effective_profile(prof, run_override={"tolerance_tighten": {"leak": "block"}})
    assert tightened_tol.tolerance.get("leak") == "block"


def test_actor_snapshot_string_false_is_parsed_as_false():
    from sopcontrol.control_profile import normalize_actor_snapshot

    raw = {
        "tier": "strong",
        "max_repairs": 5,
        "approved": "false",
        "model": "gpt-5",
    }
    norm = normalize_actor_snapshot(raw)
    assert norm["approved"] is False
    assert norm["tier"] == "unknown"
    assert norm["max_repairs"] <= 1


def test_actor_snapshot_approved_true_without_live_verification_falls_back():
    from sopcontrol.control_profile import normalize_actor_snapshot

    raw = {
        "tier": "strong",
        "max_repairs": 3,
        "approved": True,
        "source": "fixture",
        "model": "gpt-5",
    }
    norm = normalize_actor_snapshot(raw)
    assert norm["approved"] is False
    assert norm["tier"] == "unknown"
    assert norm["max_repairs"] <= 1


def test_actor_snapshot_live_verified_approved():
    from sopcontrol.control_profile import normalize_actor_snapshot

    raw = {
        "tier": "strong",
        "max_repairs": 3,
        "approved": True,
        "source": "live:eval",
        "evaluation_id": "ev-verified-999",
        "approved_by": "qa-lead",
        "model": "gpt-5",
    }
    norm = normalize_actor_snapshot(raw)
    assert norm["approved"] is True
    assert norm["tier"] == "strong"
    assert norm["max_repairs"] == 3


def test_digest_sensitive_to_declaration_presence():
    # §9.4：相同有效值、不同声明集 → digest 必须不同（absent ≠ 显式默认）
    base = normalize_profile({**BASE, "budget": {"max_audit_calls": 2, "max_repair_calls": 2}})
    no_budget = {k: v for k, v in BASE.items() if k != "budget"}
    absent = normalize_profile(no_budget)  # 未声明 budget → 继承 base
    explicit = normalize_profile({**BASE, "budget": {"max_audit_calls": 2, "max_repair_calls": 2}})
    c_absent = compose_effective_plan(_frozen_like(absent), None, base_profile=base)
    c_explicit = compose_effective_plan(_frozen_like(explicit), None, base_profile=base)
    assert c_absent.profile.budget.max_audit_calls == c_explicit.profile.budget.max_audit_calls == 2
    assert "budget.max_audit_calls" not in c_absent.layers["task"]["declared_fields"]
    assert "budget.max_audit_calls" in c_explicit.layers["task"]["declared_fields"]
    assert c_absent.digest != c_explicit.digest


def test_nested_partial_declaration_inherits_undeclared_sibling():
    # §9.5：nested object 部分声明 → 未声明子字段继承
    base = normalize_profile({**BASE, "budget": {"max_audit_calls": 4, "max_repair_calls": 4}})
    task = normalize_profile({**BASE, "budget": {"max_audit_calls": 1}})
    composed = compose_effective_plan(_frozen_like(task), None, base_profile=base)
    assert composed.profile.budget.max_audit_calls == 1      # 显式收紧
    assert composed.profile.budget.max_repair_calls == 4     # 未声明兄弟键继承

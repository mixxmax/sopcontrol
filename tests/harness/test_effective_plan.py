"""最终闭环包 A：有效计划收口反例优先（§15.1/§7.4）。

每个测试注明：初始配置 / 调用入口 / 预期 / 为什么不能 pass / 用了哪个 digest。
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sopcontrol.control_profile import (
    ProfileError,
    compose_effective_plan,
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


def test_stop_when_subset_rejected():
    base = normalize_profile({**BASE, "stop_when": ["pass", "max_rounds"]})
    fewer = normalize_profile(BASE)  # 默认只有 ["pass"] → 减少停止条件=放宽
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

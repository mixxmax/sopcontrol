"""第七批：规则可逆生命周期与路径 scope 的确定性语义。"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import shutil
import threading

import pytest

from sopcontrol.cli import main
from plugins.detectors.reachability import ReachabilityDetector
from sopcontrol.conflict import find_conflicts
from sopcontrol.model import (
    Absorption,
    Evidence,
    Finding,
    Modality,
    Rule,
    RuleLifecycleEvent,
    RuleStatus,
    SourceRef,
    effective_rules,
    rule_is_effective,
)
from sopcontrol.candidate import CandidateStore, refresh_candidates
from sopcontrol.growth import (
    ambient_grow,
    load_growth_observations,
    record_structural_observations,
)
from sopcontrol.registry import Registry, RegistryError
from sopcontrol.verdict import evaluate_rule
from sopcontrol.scope import (
    normalize_scope_paths,
    path_in_scope,
    scope_intersects,
    scope_is_strict_narrower,
)


def _rule(**overrides) -> Rule:
    values = {
        "rule_id": "LIFE-001",
        "statement": "生命周期测试规则",
        "modality": Modality.MUST,
        "status": RuleStatus.accepted,
        "source": SourceRef(type="document", ref="docs/rule.md"),
    }
    values.update(overrides)
    return Rule(**values)


def _suspend(registry: Registry, *, until: datetime, reason: str = "测试暂停") -> Rule:
    preview = registry.lifecycle_preview(
        "LIFE-001",
        action="suspend",
        reason=reason,
        actor="human-reviewer",
        until=until,
    )
    return registry.confirm_lifecycle(
        "LIFE-001",
        action="suspend",
        reason=reason,
        actor="human-reviewer",
        preview_id=preview["preview_id"],
        until=until,
    )


def test_legacy_rule_defaults_to_project_scope_and_current_revision():
    rule = _rule()

    assert rule.scope_paths == []
    assert rule.lifecycle_revision == 0
    assert rule.effective_since is None
    assert rule.suspended_until is None
    assert rule.lifecycle_events == []
    assert path_in_scope(rule.scope_paths, "src/app.py") is True


def test_suspension_boundary_is_inclusive_and_then_auto_recovers():
    until = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    rule = _rule().model_copy(update={"suspended_until": until})

    assert rule_is_effective(rule, at=until) is False
    assert rule_is_effective(rule, at=until + timedelta(microseconds=1)) is True
    assert effective_rules([rule], at=until) == []
    assert effective_rules([rule], at=until + timedelta(microseconds=1)) == [rule]


def test_non_active_status_never_becomes_effective_after_suspension_expires():
    until = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    rule = _rule().model_copy(
        update={"status": RuleStatus.deprecated, "suspended_until": until}
    )

    assert rule_is_effective(rule, at=until + timedelta(days=1)) is False


def test_scope_paths_are_normalized_and_redundant_children_removed():
    assert normalize_scope_paths(["src/app/", "src", "docs/guide.md"]) == [
        "docs/guide.md",
        "src",
    ]


@pytest.mark.parametrize(
    "path",
    ["", ".", "../src", "/tmp/src", ".sopcontrol", ".SOPCONTROL/rules", "src/../../etc"],
)
def test_scope_rejects_non_repository_or_control_plane_paths(path):
    with pytest.raises(ValueError):
        normalize_scope_paths([path])


def test_scope_contains_paths_by_component_not_string_prefix():
    scope = normalize_scope_paths(["src/app"])

    assert path_in_scope(scope, "src/app/main.py") is True
    assert path_in_scope(scope, "src/application.py") is False


def test_scope_intersection_uses_project_and_prefix_semantics():
    assert scope_intersects([], ["src"]) is True
    assert scope_intersects(["src/app"], ["src/app/api"]) is True
    assert scope_intersects(["src/app"], ["tests/app"]) is False


def test_narrowing_allows_only_strict_subsets():
    assert scope_is_strict_narrower([], ["src"]) is True
    assert scope_is_strict_narrower(["src"], ["src/app"]) is True
    assert scope_is_strict_narrower(["src"], ["src"]) is False
    assert scope_is_strict_narrower(["src/app"], ["src"]) is False
    assert scope_is_strict_narrower(["src"], ["tests"]) is False
    assert scope_is_strict_narrower(["src", "tests"], ["src"]) is True


def test_lifecycle_event_requires_aware_time():
    with pytest.raises(ValueError, match="aware UTC"):
        RuleLifecycleEvent(
            action="suspend",
            actor="human",
            reason="临时停用",
            at=datetime(2026, 9, 1, 12, 0),
            preview_id="preview",
            revision=1,
        )


def test_suspend_preview_is_read_only_and_confirmation_is_idempotent(
    tmp_path, monkeypatch
):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([_rule()])
    confirmation_time = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    until = confirmation_time + timedelta(hours=2)
    before = registry.path.read_bytes()
    # preview 也会读 utcnow 校验 until；必须在预览前冻结，否则日历越过冻结日即红
    monkeypatch.setattr("sopcontrol.registry.utcnow", lambda: confirmation_time)

    preview = registry.lifecycle_preview(
        "LIFE-001",
        action="suspend",
        reason="维护窗口",
        actor="human-reviewer",
        until=until,
    )

    assert registry.path.read_bytes() == before
    suspended = registry.confirm_lifecycle(
        "LIFE-001",
        action="suspend",
        reason="维护窗口",
        actor="human-reviewer",
        preview_id=preview["preview_id"],
        until=until,
    )
    after = registry.path.read_bytes()
    repeated = registry.confirm_lifecycle(
        "LIFE-001",
        action="suspend",
        reason="维护窗口",
        actor="human-reviewer",
        preview_id=preview["preview_id"],
        until=until,
    )

    assert suspended.status == RuleStatus.accepted
    assert suspended.suspended_until == until
    assert suspended.lifecycle_revision == 1
    assert suspended.effective_since == confirmation_time
    assert len(suspended.lifecycle_events) == 1
    assert suspended.lifecycle_events[0].preview_id == preview["preview_id"]
    assert repeated == suspended
    assert registry.path.read_bytes() == after

    with pytest.raises(RegistryError, match="scope_paths"):
        registry.confirm_lifecycle(
            "LIFE-001",
            action="suspend",
            reason="维护窗口",
            actor="human-reviewer",
            preview_id=preview["preview_id"],
            until=until,
            scope_paths=["src"],
        )
    assert registry.path.read_bytes() == after


def test_preview_binds_full_registry_and_confirmation_parameters(tmp_path, monkeypatch):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([_rule()])
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    until = now + timedelta(hours=1)
    monkeypatch.setattr("sopcontrol.registry.utcnow", lambda: now)
    preview_id = registry.lifecycle_preview(
        "LIFE-001",
        action="suspend",
        reason="维护",
        actor="human-reviewer",
        until=until,
    )["preview_id"]

    rules = registry.load()
    rules.append(_rule(rule_id="LIFE-002", statement="并发新增规则"))
    registry.save(rules)
    before = registry.path.read_bytes()

    with pytest.raises(RegistryError, match="preview_id 已失效"):
        registry.confirm_lifecycle(
            "LIFE-001",
            action="suspend",
            reason="维护",
            actor="human-reviewer",
            preview_id=preview_id,
            until=until,
        )
    assert registry.path.read_bytes() == before

    fresh = registry.lifecycle_preview(
        "LIFE-001",
        action="suspend",
        reason="维护",
        actor="human-reviewer",
        until=until,
    )["preview_id"]
    with pytest.raises(RegistryError, match="preview_id 已失效"):
        registry.confirm_lifecycle(
            "LIFE-001",
            action="suspend",
            reason="不同原因",
            actor="human-reviewer",
            preview_id=fresh,
            until=until,
        )
    assert registry.path.read_bytes() == before


@pytest.mark.parametrize("actor", ["", "  ", "agent", "AGENT"])
def test_lifecycle_preview_requires_human_actor(tmp_path, actor):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([_rule()])

    with pytest.raises(RegistryError, match="人工"):
        registry.lifecycle_preview(
            "LIFE-001",
            action="narrow",
            reason="缩窄",
            actor=actor,
            scope_paths=["src"],
        )


def test_suspend_until_must_be_aware_utc_and_later_than_confirmation(
    tmp_path, monkeypatch
):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([_rule()])
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("sopcontrol.registry.utcnow", lambda: now)

    for until in (
        datetime(2026, 9, 1, 13, 0),
        datetime(2026, 9, 1, 21, 0, tzinfo=timezone(timedelta(hours=8))),
        now,
        now - timedelta(microseconds=1),
    ):
        with pytest.raises(RegistryError, match="aware UTC|晚于确认时点"):
            registry.lifecycle_preview(
                "LIFE-001",
                action="suspend",
                reason="维护",
                actor="human-reviewer",
                until=until,
            )

    preview = registry.lifecycle_preview(
        "LIFE-001",
        action="suspend",
        reason="维护",
        actor="human-reviewer",
        until=now + timedelta(microseconds=1),
    )
    monkeypatch.setattr(
        "sopcontrol.registry.utcnow", lambda: now + timedelta(microseconds=1)
    )
    before = registry.path.read_bytes()
    with pytest.raises(RegistryError, match="晚于确认时点"):
        registry.confirm_lifecycle(
            "LIFE-001",
            action="suspend",
            reason="维护",
            actor="human-reviewer",
            preview_id=preview["preview_id"],
            until=now + timedelta(microseconds=1),
        )
    assert registry.path.read_bytes() == before


def test_reinstate_only_restores_active_rule_during_suspension(tmp_path, monkeypatch):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([_rule()])
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("sopcontrol.registry.utcnow", lambda: now)
    _suspend(registry, until=now + timedelta(hours=2))

    preview = registry.lifecycle_preview(
        "LIFE-001",
        action="reinstate",
        reason="维护提前完成",
        actor="human-reviewer",
    )
    restored = registry.confirm_lifecycle(
        "LIFE-001",
        action="reinstate",
        reason="维护提前完成",
        actor="human-reviewer",
        preview_id=preview["preview_id"],
    )

    assert restored.suspended_until is None
    assert restored.lifecycle_revision == 2
    assert [event.action for event in restored.lifecycle_events] == ["suspend", "reinstate"]
    assert restored.lifecycle_events[-1].until == now + timedelta(hours=2)
    with pytest.raises(RegistryError, match="未处于暂停窗口"):
        registry.lifecycle_preview(
            "LIFE-001",
            action="reinstate",
            reason="重复恢复",
            actor="human-reviewer",
        )


@pytest.mark.parametrize("action", ["deprecate", "supersede"])
def test_reinstate_rejects_retired_rules(tmp_path, monkeypatch, action):
    registry = Registry(tmp_path / "registry.yaml")
    rules = [_rule()]
    replacement = ""
    if action == "supersede":
        replacement = "LIFE-002"
        rules.append(_rule(rule_id=replacement, status=RuleStatus.proposed))
    registry.save(rules)
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("sopcontrol.registry.utcnow", lambda: now)
    _suspend(registry, until=now + timedelta(hours=1))
    retirement = registry.retirement_preview(
        "LIFE-001",
        action=action,
        reason="永久退出",
        actor="human-reviewer",
        replacement=replacement,
    )
    registry.confirm_retirement(
        "LIFE-001",
        action=action,
        reason="永久退出",
        actor="human-reviewer",
        preview_id=retirement["preview_id"],
        replacement=replacement,
    )

    with pytest.raises(RegistryError, match="不是 active"):
        registry.lifecycle_preview(
            "LIFE-001",
            action="reinstate",
            reason="非法恢复",
            actor="human-reviewer",
        )


def test_reinstate_rejects_expired_suspension(tmp_path, monkeypatch):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([_rule()])
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("sopcontrol.registry.utcnow", lambda: now - timedelta(hours=1))
    _suspend(registry, until=now)
    monkeypatch.setattr("sopcontrol.registry.utcnow", lambda: now)

    with pytest.raises(RegistryError, match="未处于暂停窗口"):
        registry.lifecycle_preview(
            "LIFE-001",
            action="reinstate",
            reason="已经自动恢复",
            actor="human-reviewer",
        )


def test_narrow_normalizes_scope_and_records_before_after(tmp_path, monkeypatch):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([_rule()])
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("sopcontrol.registry.utcnow", lambda: now)

    preview = registry.lifecycle_preview(
        "LIFE-001",
        action="narrow",
        reason="限定源码",
        actor="human-reviewer",
        scope_paths=["src/app", "src", "src/lib"],
    )
    narrowed = registry.confirm_lifecycle(
        "LIFE-001",
        action="narrow",
        reason="限定源码",
        actor="human-reviewer",
        preview_id=preview["preview_id"],
        scope_paths=["src/lib", "src", "src/app"],
    )

    assert narrowed.scope_paths == ["src"]
    assert narrowed.lifecycle_revision == 1
    assert narrowed.effective_since == now
    event = narrowed.lifecycle_events[-1]
    assert event.before_scope == []
    assert event.after_scope == ["src"]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (["src"], ["src"]),
        (["src/app"], ["src"]),
        (["src"], ["tests"]),
        (["src"], []),
    ],
)
def test_narrow_rejects_equal_wider_horizontal_and_project_scope(
    tmp_path, monkeypatch, before, after
):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([_rule()])
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("sopcontrol.registry.utcnow", lambda: now)
    preview = registry.lifecycle_preview(
        "LIFE-001",
        action="narrow",
        reason="建立当前 scope",
        actor="human-reviewer",
        scope_paths=before,
    )
    registry.confirm_lifecycle(
        "LIFE-001",
        action="narrow",
        reason="建立当前 scope",
        actor="human-reviewer",
        preview_id=preview["preview_id"],
        scope_paths=before,
    )
    content = registry.path.read_bytes()

    with pytest.raises(RegistryError, match="严格子集"):
        registry.lifecycle_preview(
            "LIFE-001",
            action="narrow",
            reason="非法变更",
            actor="human-reviewer",
            scope_paths=after,
        )
    assert registry.path.read_bytes() == content


def test_narrow_rejects_suspended_rule(tmp_path, monkeypatch):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([_rule()])
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("sopcontrol.registry.utcnow", lambda: now)
    _suspend(registry, until=now + timedelta(hours=1))

    with pytest.raises(RegistryError, match="effective active"):
        registry.lifecycle_preview(
            "LIFE-001",
            action="narrow",
            reason="暂停期间不能缩窄",
            actor="human-reviewer",
            scope_paths=["src"],
        )


def test_public_save_preserves_but_cannot_mutate_lifecycle_facts(
    tmp_path, monkeypatch
):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([_rule()])
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("sopcontrol.registry.utcnow", lambda: now)
    until = now + timedelta(hours=1)
    preview = registry.lifecycle_preview(
        "LIFE-001",
        action="suspend",
        reason="维护",
        actor="human-reviewer",
        until=until,
    )
    registry.confirm_lifecycle(
        "LIFE-001",
        action="suspend",
        reason="维护",
        actor="human-reviewer",
        preview_id=preview["preview_id"],
        until=until,
    )

    ordinary = registry.load()
    ordinary[0].statement = "普通说明更新"
    registry.save(ordinary)
    historical = registry.get("LIFE-001")
    assert historical.statement == "普通说明更新"
    assert historical.lifecycle_revision == 1

    mutations = (
        {"lifecycle_revision": 2},
        {"effective_since": now + timedelta(seconds=1)},
        {"suspended_until": None},
        {"scope_paths": ["src"]},
        {"lifecycle_events": []},
        {"attested_revision": 1},
    )
    before = registry.path.read_bytes()
    for update in mutations:
        rules = registry.load()
        rules[0] = rules[0].model_copy(update=update, deep=True)
        with pytest.raises(RegistryError, match="生命周期治理事实"):
            registry.save(rules)
        assert registry.path.read_bytes() == before


def test_public_save_cannot_delete_existing_rules_or_change_status(tmp_path):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([
        _rule(),
        _rule(rule_id="LIFE-002", status=RuleStatus.proposed),
    ])
    before = registry.path.read_bytes()

    with pytest.raises(RegistryError, match="不得.*删除"):
        registry.save([registry.get("LIFE-001")])
    assert registry.path.read_bytes() == before

    for status in (RuleStatus.proposed, RuleStatus.rejected):
        rules = registry.load()
        rules[0] = rules[0].model_copy(update={"status": status})
        with pytest.raises(RegistryError, match="status|生命周期迁移"):
            registry.save(rules)
        assert registry.path.read_bytes() == before

    rules = registry.load()
    rules[0].statement = "合法普通字段更新"
    registry.save(rules)
    assert registry.get("LIFE-001").statement == "合法普通字段更新"

    transitioned = registry.transition("LIFE-002", RuleStatus.clarified)
    assert transitioned.status == RuleStatus.clarified


def test_public_save_cannot_forge_or_rewrite_attestation_facts(tmp_path):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([_rule()])
    before = registry.path.read_bytes()
    forged_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    forged = {
        "source_hash": "forged-hash",
        "bypass_note": "forged note",
        "attested_by": "forger",
        "attested_at": forged_at,
        "attested_revision": 0,
    }
    for field, value in forged.items():
        rules = registry.load()
        rules[0] = rules[0].model_copy(update={field: value})
        with pytest.raises(RegistryError, match="确认书"):
            registry.save(rules)
        assert registry.path.read_bytes() == before

    attested = registry.record_attestation(
        "LIFE-001",
        source_hash="real-hash",
        bypass_note="人工分析过绕过路径",
        actor="human-reviewer",
        at=forged_at,
    )
    assert attested.source_hash == "real-hash"
    assert attested.bypass_note == "人工分析过绕过路径"
    assert attested.attested_by == "human-reviewer"
    assert attested.attested_at == forged_at
    assert attested.attested_revision == attested.lifecycle_revision

    attested_bytes = registry.path.read_bytes()
    for field, value in {
        "source_hash": "rewritten",
        "bypass_note": "rewritten",
        "attested_by": "other-human",
        "attested_at": forged_at + timedelta(seconds=1),
        "attested_revision": None,
    }.items():
        rules = registry.load()
        rules[0] = rules[0].model_copy(update={field: value})
        with pytest.raises(RegistryError, match="确认书"):
            registry.save(rules)
        assert registry.path.read_bytes() == attested_bytes


def test_registry_attestation_requires_human_actor_and_complete_facts(tmp_path):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([_rule()])
    at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    before = registry.path.read_bytes()

    for actor in ("", "  ", "agent", " AGENT "):
        with pytest.raises(RegistryError, match="人工"):
            registry.record_attestation(
                "LIFE-001",
                source_hash="source-hash",
                bypass_note="绕过分析",
                actor=actor,
                at=at,
            )
        assert registry.path.read_bytes() == before

    for source_hash, bypass_note in (("", "绕过分析"), ("source-hash", "  ")):
        with pytest.raises(RegistryError, match="确认书"):
            registry.record_attestation(
                "LIFE-001",
                source_hash=source_hash,
                bypass_note=bypass_note,
                actor="human-reviewer",
                at=at,
            )
        assert registry.path.read_bytes() == before


def test_already_suspended_rule_cannot_start_or_extend_another_window(
    tmp_path, monkeypatch
):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([_rule()])
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("sopcontrol.registry.utcnow", lambda: now)
    first_until = now + timedelta(hours=1)
    _suspend(registry, until=first_until)
    before = registry.path.read_bytes()

    for until in (now + timedelta(minutes=30), now + timedelta(hours=2)):
        with pytest.raises(RegistryError, match="已处于暂停窗口|reinstate|自动恢复"):
            registry.lifecycle_preview(
                "LIFE-001",
                action="suspend",
                reason="覆盖暂停窗口",
                actor="human-reviewer",
                until=until,
            )
        assert registry.path.read_bytes() == before


def _scoped_rule(scope_paths, **overrides):
    at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    return _rule(
        scope_paths=scope_paths,
        lifecycle_revision=1,
        effective_since=at,
        lifecycle_events=[RuleLifecycleEvent(
            action="narrow",
            actor="human-reviewer",
            reason="建立路径作用域",
            at=at,
            preview_id=f"scope-{'-'.join(scope_paths)}",
            revision=1,
            before_scope=[],
            after_scope=scope_paths,
        )],
        **overrides,
    )


def test_supersede_replacement_scope_must_cover_every_retiring_path(tmp_path):
    registry = Registry(tmp_path / "registry.yaml")
    old = _scoped_rule(["src", "tests"])

    for replacement_scope in (["docs"], ["src"]):
        replacement = _scoped_rule(
            replacement_scope, rule_id="LIFE-002", status=RuleStatus.proposed
        )
        registry._write([old, replacement])
        with pytest.raises(RegistryError, match="覆盖|作用域"):
            registry.retirement_preview(
                "LIFE-001",
                action="supersede",
                reason="替换",
                actor="human-reviewer",
                replacement="LIFE-002",
            )

    for replacement_scope in (["src", "tests"], []):
        replacement = (
            _scoped_rule(
                replacement_scope, rule_id="LIFE-002", status=RuleStatus.proposed
            )
            if replacement_scope
            else _rule(rule_id="LIFE-002", status=RuleStatus.proposed)
        )
        registry._write([old, replacement])
        preview = registry.retirement_preview(
            "LIFE-001",
            action="supersede",
            reason="替换",
            actor="human-reviewer",
            replacement="LIFE-002",
        )
        assert preview["replacement"] == "LIFE-002"


def test_project_scope_can_only_be_superseded_by_project_scope(tmp_path):
    registry = Registry(tmp_path / "registry.yaml")
    old = _rule()
    narrow = _scoped_rule(
        ["src"], rule_id="LIFE-002", status=RuleStatus.proposed
    )
    registry._write([old, narrow])

    with pytest.raises(RegistryError, match="project|覆盖|作用域"):
        registry.retirement_preview(
            "LIFE-001",
            action="supersede",
            reason="替换",
            actor="human-reviewer",
            replacement="LIFE-002",
        )

    registry._write([old, _rule(rule_id="LIFE-002", status=RuleStatus.proposed)])
    preview = registry.retirement_preview(
        "LIFE-001",
        action="supersede",
        reason="替换",
        actor="human-reviewer",
        replacement="LIFE-002",
    )
    assert preview["replacement"] == "LIFE-002"


def test_confirm_retirement_rejects_invalid_action_before_idempotent_return(tmp_path):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([_rule()])
    preview = registry.retirement_preview(
        "LIFE-001",
        action="deprecate",
        reason="永久退出",
        actor="human-reviewer",
    )
    retired = registry.confirm_retirement(
        "LIFE-001",
        action="deprecate",
        reason="永久退出",
        actor="human-reviewer",
        preview_id=preview["preview_id"],
    )
    before = registry.path.read_bytes()

    with pytest.raises(RegistryError, match="未知规则退出动作"):
        registry.confirm_retirement(
            "LIFE-001",
            action="invalid",
            reason="永久退出",
            actor="human-reviewer",
            preview_id=retired.retirement_id,
        )
    assert registry.path.read_bytes() == before


def test_public_add_and_initial_save_reject_lifecycle_injection(tmp_path):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([_rule()])

    injected = _rule(rule_id="LIFE-002").model_copy(
        update={"scope_paths": ["src"]}
    )
    with pytest.raises(RegistryError, match="生命周期治理事实"):
        registry.add(injected)
    with pytest.raises(RegistryError, match="生命周期治理事实"):
        Registry(tmp_path / "other.yaml").save([injected])

    legacy = _rule(rule_id="LIFE-LEGACY", scope="ci.deploy")
    registry.add(legacy)
    assert registry.get("LIFE-LEGACY").scope == "ci.deploy"
    assert registry.get("LIFE-LEGACY").scope_paths == []


def test_concurrent_lifecycle_previews_allow_only_first_registry_change(
    tmp_path, monkeypatch
):
    registry_a = Registry(tmp_path / "registry.yaml")
    registry_b = Registry(tmp_path / "registry.yaml")
    registry_a.save([_rule(), _rule(rule_id="LIFE-002")])
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("sopcontrol.registry.utcnow", lambda: now)
    preview_a = registry_a.lifecycle_preview(
        "LIFE-001",
        action="narrow",
        reason="A",
        actor="human-reviewer",
        scope_paths=["src"],
    )["preview_id"]
    preview_b = registry_b.lifecycle_preview(
        "LIFE-002",
        action="narrow",
        reason="B",
        actor="human-reviewer",
        scope_paths=["tests"],
    )["preview_id"]
    first_at_write = threading.Event()
    release_first = threading.Event()
    original_write = Registry._write

    def controlled_write(self, rules):
        if threading.current_thread().name == "lifecycle-a":
            first_at_write.set()
            assert release_first.wait(timeout=5)
        original_write(self, rules)

    monkeypatch.setattr(Registry, "_write", controlled_write)
    successes = []
    errors = []

    def confirm(registry, rule_id, reason, preview_id, scope_paths):
        try:
            registry.confirm_lifecycle(
                rule_id,
                action="narrow",
                reason=reason,
                actor="human-reviewer",
                preview_id=preview_id,
                scope_paths=scope_paths,
            )
            successes.append(rule_id)
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(
        target=confirm,
        name="lifecycle-a",
        args=(registry_a, "LIFE-001", "A", preview_a, ["src"]),
    )
    second = threading.Thread(
        target=confirm,
        name="lifecycle-b",
        args=(registry_b, "LIFE-002", "B", preview_b, ["tests"]),
    )
    first.start()
    assert first_at_write.wait(timeout=5)
    second.start()
    release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert successes == ["LIFE-001"]
    assert len(errors) == 1
    assert isinstance(errors[0], RegistryError)
    assert "preview_id 已失效" in str(errors[0])
    assert registry_a.get("LIFE-001").scope_paths == ["src"]
    assert registry_a.get("LIFE-002").scope_paths == []


def _cli_work(tmp_path):
    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/ci-deploy", work)
    return work


def _preview_id(output: str) -> str:
    match = re.search(r"preview_id:\s*([0-9a-f]{16})", output)
    assert match, output
    return match.group(1)


def _lifecycle_command(work, action="suspend"):
    command = [
        "rule",
        action,
        "DEPLOY-001",
        str(work),
        "--reason",
        "临时维护",
        "--by",
        "human-reviewer",
    ]
    if action == "suspend":
        command += ["--until", "2099-09-01T12:00:00Z"]
    elif action == "narrow":
        command += ["--scope", "scripts"]
    return command


def test_cli_lifecycle_preview_is_read_only_and_explains_impact(tmp_path, capsys):
    work = _cli_work(tmp_path)
    tracked = [
        work / ".sopcontrol/rules/registry.yaml",
        work / "AGENTS.md",
        work / "CLAUDE.md",
    ]
    before = {path: path.read_bytes() if path.exists() else None for path in tracked}

    assert main(_lifecycle_command(work)) == 0
    output = capsys.readouterr().out

    assert "before scope: project" in output
    assert "after scope: project" in output
    assert "until: 2099-09-01T12:00:00+00:00" in output
    assert "受影响消费者" in output
    assert "受影响任务" in output
    assert "受影响 guard" in output
    assert "投影目标: AGENTS.md, CLAUDE.md" in output
    assert "静态 invariant guard 保留" in output
    assert "未修改任何文件" in output
    assert {path: path.read_bytes() if path.exists() else None for path in tracked} == before


def test_cli_lifecycle_confirmation_and_stale_preview(tmp_path, capsys):
    work = _cli_work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    command = _lifecycle_command(work)
    assert main(command) == 0
    preview_id = _preview_id(capsys.readouterr().out)

    assert main(command + ["--confirm-preview", preview_id]) == 0
    assert registry.get("DEPLOY-001").suspended_until == datetime(
        2099, 9, 1, 12, 0, tzinfo=timezone.utc
    )
    agents = (work / "AGENTS.md").read_text(encoding="utf-8")
    # 暂停规则不得再进「必须遵守」硬规则核；编年「何以至此」仍可提及
    hard = agents.split("## 必须遵守的规则")[1].split("## ")[0] if "## 必须遵守的规则" in agents else agents
    assert "DEPLOY-001" not in hard

    work = _cli_work(tmp_path / "stale")
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    command = _lifecycle_command(work)
    assert main(command) == 0
    stale_id = _preview_id(capsys.readouterr().out)
    rules = registry.load()
    rules[0].statement += "（已变化）"
    registry.save(rules)
    before = registry.path.read_bytes()

    assert main(command + ["--confirm-preview", stale_id]) == 2
    assert "preview_id 已失效" in capsys.readouterr().err
    assert registry.path.read_bytes() == before


def test_cli_reinstate_and_narrow_confirm_through_same_transaction(tmp_path, capsys):
    work = _cli_work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    suspend = _lifecycle_command(work)
    assert main(suspend) == 0
    preview_id = _preview_id(capsys.readouterr().out)
    assert main(suspend + ["--confirm-preview", preview_id]) == 0
    capsys.readouterr()

    reinstate = _lifecycle_command(work, "reinstate")
    assert main(reinstate) == 0
    preview_id = _preview_id(capsys.readouterr().out)
    assert main(reinstate + ["--confirm-preview", preview_id]) == 0
    assert registry.get("DEPLOY-001").suspended_until is None
    capsys.readouterr()

    narrow = _lifecycle_command(work, "narrow")
    assert main(narrow) == 0
    output = capsys.readouterr().out
    assert "before scope: project" in output
    assert "after scope: scripts" in output
    preview_id = _preview_id(output)
    assert main(narrow + ["--confirm-preview", preview_id]) == 0
    assert registry.get("DEPLOY-001").scope_paths == ["scripts"]
    assert "作用域: scripts" in (work / "AGENTS.md").read_text(encoding="utf-8")


def test_cli_lifecycle_projection_failure_restores_exact_bytes(
    tmp_path, capsys, monkeypatch
):
    work = _cli_work(tmp_path)
    assert main(["project", "all", str(work)]) == 0
    capsys.readouterr()
    command = _lifecycle_command(work, "narrow")
    assert main(command) == 0
    preview_id = _preview_id(capsys.readouterr().out)
    tracked = [
        work / ".sopcontrol/rules/registry.yaml",
        work / "AGENTS.md",
        work / "CLAUDE.md",
    ]
    before = {path: path.read_bytes() for path in tracked}

    import sopcontrol.project

    monkeypatch.setattr(
        sopcontrol.project,
        "write_all_projections",
        lambda root: (_ for _ in ()).throw(OSError("disk full")),
    )
    assert main(command + ["--confirm-preview", preview_id]) == 2
    error = capsys.readouterr().err
    assert str(work / "AGENTS.md") in error
    assert str(work / "CLAUDE.md") in error
    assert "已回滚" in error
    assert {path: path.read_bytes() for path in tracked} == before


def test_cli_lifecycle_reports_restore_failure_with_full_path(
    tmp_path, capsys, monkeypatch
):
    work = _cli_work(tmp_path)
    assert main(["project", "all", str(work)]) == 0
    capsys.readouterr()
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    command = _lifecycle_command(work, "narrow")
    assert main(command) == 0
    preview_id = _preview_id(capsys.readouterr().out)

    import sopcontrol.project

    monkeypatch.setattr(
        sopcontrol.project,
        "write_all_projections",
        lambda root: (_ for _ in ()).throw(OSError("projection failed")),
    )
    original_write_bytes = Path.write_bytes

    def fail_registry_restore(path, content):
        if path == registry.path:
            raise OSError("registry restore failed")
        return original_write_bytes(path, content)

    monkeypatch.setattr(Path, "write_bytes", fail_registry_restore)
    assert main(command + ["--confirm-preview", preview_id]) == 2
    error = capsys.readouterr().err
    assert "未恢复" in error
    assert str(registry.path) in error
    assert "已回滚" not in error


@pytest.mark.parametrize(
    "extra",
    [
        ["--until", "not-an-iso-time"],
        ["--until", "2099-09-01T12:00:00+08:00"],
    ],
)
def test_cli_suspend_rejects_invalid_until_without_writes(tmp_path, capsys, extra):
    work = _cli_work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    before = registry.path.read_bytes()
    command = [
        "rule", "suspend", "DEPLOY-001", str(work),
        "--reason", "维护", "--by", "human-reviewer", *extra,
    ]

    assert main(command) == 2
    assert "until" in capsys.readouterr().err
    assert registry.path.read_bytes() == before


def test_cli_narrow_rejects_control_plane_scope_without_writes(tmp_path, capsys):
    work = _cli_work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    before = registry.path.read_bytes()

    assert main([
        "rule", "narrow", "DEPLOY-001", str(work),
        "--scope", ".sopcontrol/rules", "--reason", "非法", "--by", "human-reviewer",
    ]) == 2
    assert "控制面" in capsys.readouterr().err
    assert registry.path.read_bytes() == before


def test_rule_list_distinguishes_suspension_auto_recovery_and_path_scope(
    tmp_path, capsys, monkeypatch
):
    work = _cli_work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("sopcontrol.registry.utcnow", lambda: now)
    preview = registry.lifecycle_preview(
        "DEPLOY-001", action="suspend", reason="维护", actor="human-reviewer",
        until=now + timedelta(hours=1),
    )
    registry.confirm_lifecycle(
        "DEPLOY-001", action="suspend", reason="维护", actor="human-reviewer",
        preview_id=preview["preview_id"], until=now + timedelta(hours=1),
    )

    monkeypatch.setattr("sopcontrol.cli_rules.utcnow", lambda: now)
    assert main(["rule", "list", str(work)]) == 0
    assert "暂停至 2026-09-01T13:00:00+00:00" in capsys.readouterr().out

    monkeypatch.setattr("sopcontrol.cli_rules.utcnow", lambda: now + timedelta(hours=2))
    assert main(["rule", "list", str(work)]) == 0
    assert "自动恢复" in capsys.readouterr().out


def test_scope_outside_marker_cannot_support_rule_verdict():
    rule = _rule(consumer_markers=["governed_marker"]).model_copy(
        update={"scope_paths": ["src"]}
    )
    outside = Evidence(
        kind="ast_scan.references",
        subject="vendor/outside.py",
        observed=["governed_marker"],
        observer="ast_scan",
        input_hash="outside",
    )

    verdict = evaluate_rule(rule, [outside], [])

    assert verdict.status == "gap"
    assert verdict.absorption == Absorption.documented
    assert outside.evidence_id not in verdict.evidence_ids


def test_opposite_rules_in_disjoint_scopes_do_not_conflict():
    candidate = _rule(
        rule_id="SCOPE-MUST",
        modality=Modality.MUST,
        consumer_markers=["shared_gate"],
    ).model_copy(update={"scope_paths": ["src"]})
    other = _rule(
        rule_id="SCOPE-MUST-NOT",
        modality=Modality.MUST_NOT,
        consumer_markers=["shared_gate"],
    ).model_copy(update={"scope_paths": ["tests"]})

    assert find_conflicts(candidate, [other]) == []

    overlapping = other.model_copy(update={"scope_paths": ["src/api"]})
    assert [item["other_id"] for item in find_conflicts(candidate, [overlapping])] == [
        "SCOPE-MUST-NOT"
    ]


def test_reachability_does_not_use_import_bridge_outside_scope():
    rule = _rule(consumer_markers=["governed_marker"]).model_copy(
        update={"scope_paths": ["src", "tests"]}
    )
    evidence = [
        Evidence(
            kind="ast_scan.references",
            subject="src/gate.py",
            observed=["governed_marker"],
            observer="ast_scan",
            input_hash="prod",
        ),
        Evidence(
            kind="ast_scan.references",
            subject="tests/test_gate.py",
            observed=["governed_marker"],
            observer="ast_scan",
            input_hash="test",
        ),
        Evidence(
            kind="import_graph.imports",
            subject="tests/test_gate.py",
            observed=["bridge"],
            observer="import_graph",
            input_hash="test-import",
        ),
        Evidence(
            kind="import_graph.imports",
            subject="vendor/bridge.py",
            observed=["gate"],
            observer="import_graph",
            input_hash="outside-bridge",
        ),
    ]

    findings = ReachabilityDetector().detect([rule], evidence)

    assert any(item.pattern_id == "test_cannot_reach_consumer" for item in findings)


def test_lifecycle_and_retirement_previews_report_dry_run_impact(tmp_path):
    registry = Registry(tmp_path / "registry.yaml")
    rules = [
        _rule(
            rule_id="IMP-001",
            guard_ids=["GUARD-PUSH-GATE"],
            consumer_markers=["imp_one"],
        ),
        _rule(
            rule_id="IMP-002",
            guard_ids=["GUARD-PUSH-GATE"],
            consumer_markers=["imp_two"],
        ),
        _rule(
            rule_id="IMP-003",
            guard_ids=["GUARD-EXECUTOR-IDENTITY"],
            consumer_markers=["imp_three"],
        ),
    ]
    registry.save(rules)

    suspend = registry.lifecycle_preview(
        "IMP-001", action="suspend", reason="维护", actor="human-reviewer",
        until=datetime(2099, 9, 1, tzinfo=timezone.utc),
    )
    impact = suspend["impact"]
    assert impact["effective_rules_lost"] == ["IMP-001"]
    # IMP-002 仍声明同一 guard：PUSH-GATE 治理记录不消失；列表只含目标自身 guard
    assert impact["guards_losing_last_rule"] == []

    retire = registry.retirement_preview(
        "IMP-003", action="deprecate", reason="退出", actor="human-reviewer",
    )
    assert retire["impact"]["effective_rules_lost"] == ["IMP-003"]
    assert retire["impact"]["guards_losing_last_rule"] == ["GUARD-EXECUTOR-IDENTITY"]

    supersede = registry.retirement_preview(
        "IMP-001", action="supersede", reason="接管", actor="human-reviewer",
        replacement="IMP-002",
    )
    assert supersede["impact"]["effective_rules_lost"] == ["IMP-001"]
    # replacement 仍声明同一 guard：不产生失去治理记录的 guard
    assert supersede["impact"]["guards_losing_last_rule"] == []


def test_cli_lifecycle_preview_prints_dry_run_impact(tmp_path, capsys):
    work = _cli_work(tmp_path)
    assert main(_lifecycle_command(work)) == 0
    output = capsys.readouterr().out
    assert "将退出当前有效集合: DEPLOY-001" in output
    assert "失去最后治理记录的 guard: 无" in output


def _fresh_ambient(work):
    """fixture 磁盘态可能带历史 ambient 产物；副本内重置，保证阈值语义确定性。"""
    for rel in (
        ".sopcontrol/evidence/growth-observations.jsonl",
        ".sopcontrol/evidence/growth-state.yaml",
        ".sopcontrol/evidence/space-snapshots.jsonl",
        ".sopcontrol/evidence/project-events.jsonl",
        ".sopcontrol/rules/candidates.yaml",
    ):
        (work / rel).unlink(missing_ok=True)


def test_legacy_cleared_materializes_retire_rule_candidate(tmp_path):
    work = _cli_work(tmp_path)
    _fresh_ambient(work)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    target = registry.get("RELEASE-001")
    assert target.legacy_markers

    for index in range(6):
        record_structural_observations(
            work,
            rules=registry.load(),
            findings=[],
            round_id=f"legacy-clear-{index}",
        )
    refresh_candidates(work)

    store = CandidateStore(work)
    retire = [
        record for record in store.load()
        if record.suggested_action == "retire_rule"
        and "RELEASE-001" in record.statement
    ]
    assert len(retire) == 1
    assert "deprecate RELEASE-001" in retire[0].statement
    # 候选永不写 registry：目标规则保持 accepted
    assert registry.get("RELEASE-001").status == RuleStatus.accepted


def test_legacy_cleared_candidate_requires_threshold_rounds(tmp_path):
    work = _cli_work(tmp_path)
    _fresh_ambient(work)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    for index in range(5):
        record_structural_observations(
            work,
            rules=registry.load(),
            findings=[],
            round_id=f"short-{index}",
        )
    refresh_candidates(work)
    store = CandidateStore(work)
    # fixture 预置的久悬 gap 候选与本题无关；只断言 RELEASE-001 的 legacy 清零候选未物化
    assert not [
        record for record in store.load()
        if record.suggested_action == "retire_rule"
        and "RELEASE-001" in record.statement
    ]


def test_legacy_cleared_observation_skips_round_with_live_legacy(tmp_path):
    work = _cli_work(tmp_path)
    _fresh_ambient(work)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    live = Finding(
        pattern_id="legacy_entry_alive",
        rule_id="RELEASE-001",
        summary="旧入口仍存活",
        detector="no_consumer",
    )
    for index in range(6):
        findings = [live] if index == 3 else []
        record_structural_observations(
            work,
            rules=registry.load(),
            findings=findings,
            round_id=f"mixed-{index}",
        )
    refresh_candidates(work)
    store = CandidateStore(work)
    assert not [
        record for record in store.load()
        if record.suggested_action == "retire_rule"
        and "RELEASE-001" in record.statement
    ]


def test_ambient_grow_records_legacy_cleared_structural_observations(tmp_path):
    work = _cli_work(tmp_path)
    _fresh_ambient(work)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    ambient_grow(work, findings=[], round_id="ambient-1")
    patterns = {
        obs.pattern_id for obs in load_growth_observations(work)
    }
    assert "legacy_cleared" in patterns
    assert registry.get("RELEASE-001").status == RuleStatus.accepted


def test_retire_candidate_fingerprint_is_stable_across_rounds(tmp_path):
    """轮数写进 statement 会进入指纹：阈值后每轮物化新候选而非聚合
    （合并验收非阻断 2）。指纹必须轮数无关。"""
    work = _cli_work(tmp_path)
    _fresh_ambient(work)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")

    for index in range(6):
        record_structural_observations(
            work, rules=registry.load(), findings=[], round_id=f"stable-{index}"
        )
    refresh_candidates(work)
    store = CandidateStore(work)
    first = [
        record for record in store.load()
        if record.suggested_action == "retire_rule"
        and "RELEASE-001" in record.statement
    ]
    assert len(first) == 1

    for index in range(3):
        record_structural_observations(
            work, rules=registry.load(), findings=[], round_id=f"stable-more-{index}"
        )
    refresh_candidates(work)
    again = [
        record for record in store.load()
        if record.suggested_action == "retire_rule"
        and "RELEASE-001" in record.statement
    ]
    assert len(again) == 1
    assert again[0].candidate_id == first[0].candidate_id

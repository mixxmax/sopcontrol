"""§12.5 升级矩阵：绑定清单、语义 diff 硬门、影子验证、原子切换、回滚。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sopcontrol.cli import main
from sopcontrol.model import Modality, Rule, RuleStatus, SourceRef
from sopcontrol.registry import Registry
from sopcontrol.upgrade import (
    ProjectBinding,
    SemanticProjection,
    init_binding,
    load_binding,
    plan_upgrade,
    rollback,
    semantic_diff,
    sync,
)


@pytest.fixture()
def project(tmp_path):
    assert main(["init", str(tmp_path)]) == 0
    return tmp_path


def _add_dynamic_rule(root: Path, rule_id: str) -> None:
    reg = Registry(root / ".sopcontrol" / "rules" / "registry.yaml")
    reg.add(Rule(rule_id=rule_id, statement="动态规则", modality=Modality.MUST,
                 status=RuleStatus.proposed, rule_class="dynamic_sop",
                 source=SourceRef(type="user_conversation", ref="s1")))
    reg.transition(rule_id, RuleStatus.accepted)
    reg.transition(rule_id, RuleStatus.compiled)


def test_binding_init_and_load(project):
    binding = init_binding(project)
    assert binding.core_version
    loaded = load_binding(project)
    assert loaded is not None and loaded.core_version == binding.core_version
    # 绑定不含 secret（模型字段无该类字段——结构保证）
    assert not hasattr(binding, "secret")


def test_zero_diff_patch_upgrade_auto_switches(project):
    """§8.5 patch 零语义差异：一次用户动作完成升级，规则 100% 保留。"""
    _add_dynamic_rule(project, "DR-001")
    from sopcontrol.upgrade import save_binding

    binding = init_binding(project)
    binding.core_version = "0.2.9"  # 模拟旧版本绑定
    save_binding(project, binding)
    result = sync(project, target_version="0.3.0", assume_yes=True)
    assert result["outcome"] == "switched"
    assert result["semantic_diff"]["semantic_changes"] is False
    rules = Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load()
    assert [r.rule_id for r in rules if r.rule_class == "dynamic_sop"] == ["DR-001"]
    # 回滚点已保存
    loaded = load_binding(project)
    assert loaded.previous_runtime_path


def test_rule_loss_blocks_auto_switch(project):
    """§8.4 硬门：升级导致动态 SOP 丢失 → 阻断切换，旧 runtime 保持。"""
    _add_dynamic_rule(project, "DR-KEEP")
    before = SemanticProjection.capture(project, "0.3.0")
    after = before.model_copy(deep=True)
    after.dynamic_sop_ids = []  # 模拟 staged 运行时丢规则
    diff = semantic_diff(before, after)
    assert diff["downgrades"] and any("动态 SOP 丢失" in d for d in diff["downgrades"])
    plan = plan_upgrade.__wrapped__ if hasattr(plan_upgrade, "__wrapped__") else plan_upgrade
    # 经 monkeypatch 模拟 staged 投影丢规则
    import sopcontrol.upgrade as up

    real = up.SemanticProjection.capture

    def fake_capture(root, version):
        if version == "9.9.9":
            return after
        return real(root, version)

    up.SemanticProjection.capture = staticmethod(fake_capture)
    try:
        result = sync(project, target_version="9.9.9", assume_yes=True)
    finally:
        up.SemanticProjection.capture = staticmethod(real)
    assert result["outcome"] == "blocked"
    assert result["switched"] is False
    # 旧绑定未被动过
    loaded = load_binding(project)
    assert loaded.core_version != "9.9.9"


def test_block_downgrade_blocks_switch(project):
    before = SemanticProjection.capture(project, "0.3.0")
    after = before.model_copy(deep=True)
    after.block_modalities = before.block_modalities - 1
    diff = semantic_diff(before, after)
    assert any("block 级规则" in d for d in diff["downgrades"])


def test_semantic_change_awaits_confirmation(project):
    """§8.5 minor/语义变化：展示一次摘要确认，不静默切换。"""
    binding = load_binding(project) or init_binding(project)
    import sopcontrol.upgrade as up

    real = up.SemanticProjection.capture

    def fake_capture(root, version):
        proj = real(root, version)
        if version == "0.4.0":
            proj = proj.model_copy(deep=True)
            proj.digest = "changed-" + proj.digest  # 模拟语义变化
        return proj

    up.SemanticProjection.capture = staticmethod(fake_capture)
    try:
        result = sync(project, target_version="0.4.0", assume_yes=False)
    finally:
        up.SemanticProjection.capture = staticmethod(real)
    assert result["outcome"] == "awaiting_confirmation"
    assert result["switched"] is False
    # 用户确认（--yes）后切换
    result2 = sync(project, target_version="0.4.0", assume_yes=True)
    assert result2["outcome"] == "switched"


def test_rollback_restores_previous_version(project):
    from sopcontrol.upgrade import save_binding

    binding = init_binding(project)
    binding.core_version = "0.2.9"
    save_binding(project, binding)
    result = sync(project, target_version="0.3.0", assume_yes=True)
    assert result["switched"] is True
    rb = rollback(project)
    assert rb["rolled_back"] is True
    loaded = load_binding(project)
    assert loaded.core_version == "0.2.9"
    # 再回滚（无更早回滚点）：互换回来
    rb2 = rollback(project)
    assert rb2["rolled_back"] is True


def test_rollback_refused_if_dynamic_sop_lost(project):
    _add_dynamic_rule(project, "DR-STAY")
    binding = load_binding(project) or init_binding(project)
    binding.previous_runtime_path = "/runtimes/9.8.0"
    from sopcontrol.upgrade import save_binding
    save_binding(project, binding)
    import sopcontrol.upgrade as up

    real = up.SemanticProjection.capture

    def fake_capture(root, version):
        proj = real(root, version)
        if version == "9.8.0":
            proj = proj.model_copy(deep=True)
            proj.dynamic_sop_ids = []  # 旧 runtime 缺该规则类
        return proj

    up.SemanticProjection.capture = staticmethod(fake_capture)
    try:
        rb = rollback(project)
    finally:
        up.SemanticProjection.capture = staticmethod(real)
    assert rb["rolled_back"] is False
    assert "动态 SOP" in rb["note"]


def test_sync_cli_end_to_end(project, capsys, monkeypatch):
    monkeypatch.chdir(project)
    binding = init_binding(project)
    from sopcontrol.upgrade import save_binding
    binding.core_version = "0.2.9"
    save_binding(project, binding)
    assert main(["sync", "--yes"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["switched"] is True
    assert main(["rollback"]) == 0
    out2 = json.loads(capsys.readouterr().out)
    assert out2["rolled_back"] is True


def _capture_with_mutation(project, mutate, *, expect_digest_change=True):
    from sopcontrol.upgrade import SemanticProjection as _SP

    before = _SP.capture(project, "0.3.0")
    reg = Registry(project / ".sopcontrol" / "rules" / "registry.yaml")
    rules = reg.load()
    mutate(next(r for r in rules if r.rule_id == "SEM-1"))
    reg.save(rules)
    after = _SP.capture(project, "0.3.0")
    if expect_digest_change:
        assert before.digest != after.digest  # harness 前提：digest 真变了
    return before, after


def _seed_sem_rule(project):
    _add_dynamic_rule(project, "SEM-1")
    from sopcontrol.upgrade import SemanticProjection as _SP

    assert _SP.capture(project, "0.3.0").digest


def test_semantic_change_statement_detected(project):
    _seed_sem_rule(project)
    before, after = _capture_with_mutation(
        project, lambda r: setattr(r, "statement", r.statement + "（修订）"))
    diff = semantic_diff(before, after)
    assert diff["semantic_changes"] is True
    assert any(c["rule_id"] == "SEM-1" and "statement" in c["changed_fields"]
               for c in diff["changed_rules"])


def test_semantic_change_activation_detected(project):
    _seed_sem_rule(project)
    before, after = _capture_with_mutation(
        project, lambda r: r.activation.actions.append("other.action"))
    diff = semantic_diff(before, after)
    assert diff["semantic_changes"] is True
    assert any("activation" in c["changed_fields"] for c in diff["changed_rules"])


def test_semantic_change_flexibility_bound_detected(project):
    _seed_sem_rule(project)

    def mutate(r):
        r.flexibility.upper_bound = "最多修正一轮"

    before, after = _capture_with_mutation(project, mutate)
    diff = semantic_diff(before, after)
    assert any("flexibility" in c["changed_fields"] for c in diff["changed_rules"])


def test_semantic_change_modality_detected(project):
    from sopcontrol.model import Modality as _Modality

    _seed_sem_rule(project)
    before, after = _capture_with_mutation(
        project, lambda r: setattr(r, "modality", _Modality.SHOULD))
    diff = semantic_diff(before, after)
    assert any("modality" in c["changed_fields"] for c in diff["changed_rules"])


def _sem_rule(**kw):
    from sopcontrol.model import Modality as _Modality
    from sopcontrol.model import Rule as _Rule
    from sopcontrol.model import RuleStatus as _RS
    from sopcontrol.model import SourceRef as _SR

    base = {"rule_id": "SEM-1", "statement": "动态规则",
            "modality": _Modality.MUST, "status": _RS.compiled,
            "rule_class": "dynamic_sop", "source": _SR(ref="s1")}
    base.update(kw)
    return _Rule(**base)


def test_semantic_change_scope_detected(project):
    from sopcontrol.upgrade import RuleProjection, semantic_diff
    from sopcontrol.upgrade import SemanticProjection as _SP

    _seed_sem_rule(project)
    before = _SP.capture(project, "0.3.0")
    mutated = _sem_rule()
    mutated.scope_paths = ["docs/"]
    after = _SP(
        core_version="0.3.0", rule_schema_version=before.rule_schema_version,
        total_rules=1, active_rules=1,
        rules=[RuleProjection.of(mutated)],
        digest="x")
    after2 = _SP.capture(project, "0.3.0")
    assert after2.digest == before.digest  # 仓库未变时 digest 稳定（对照）
    diff = semantic_diff(before, after)
    assert any("scope" in c["changed_fields"] for c in diff["changed_rules"])


def test_semantic_change_status_detected(project):
    from sopcontrol.model import RuleStatus as _RS
    from sopcontrol.upgrade import semantic_diff
    from sopcontrol.upgrade import SemanticProjection as _SP

    _seed_sem_rule(project)
    before = _SP.capture(project, "0.3.0")
    reg = Registry(project / ".sopcontrol" / "rules" / "registry.yaml")
    reg.transition("SEM-1", _RS.activated)  # 合法迁移路径
    after = _SP.capture(project, "0.3.0")
    assert before.digest != after.digest
    diff = semantic_diff(before, after)
    assert any("status" in c["changed_fields"] for c in diff["changed_rules"])


def test_semantic_change_consumer_guard_detected(project):
    _seed_sem_rule(project)

    def mutate(r):
        r.consumer_markers.append("probe-x")
        r.guard_ids.append("guard-y")

    before, after = _capture_with_mutation(project, mutate)
    diff = semantic_diff(before, after)
    fields = [f for c in diff["changed_rules"] for f in c["changed_fields"]]
    assert "consumer_markers" in fields and "guard_ids" in fields


def test_time_only_change_no_semantic_change(project):
    from datetime import datetime, timezone

    _seed_sem_rule(project)

    def mutate(r):
        r.accepted_at = datetime.now(timezone.utc)

    before, after = _capture_with_mutation(project, mutate,
                                             expect_digest_change=False)
    diff = semantic_diff(before, after)
    assert diff["semantic_changes"] is False
    assert diff["changed_rules"] == []

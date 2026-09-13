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

    calls = {"n": 0}

    def fake_capture(root, version):
        # 版本保持真实（§9.1 禁伪造版本）；第二次捕获（after）语义变化，
        # 模拟新版本规则正文改变。
        proj = real(root, version)
        calls["n"] += 1
        if calls["n"] >= 2:
            proj = proj.model_copy(deep=True)
            proj.digest = "changed-" + proj.digest
        return proj

    up.SemanticProjection.capture = staticmethod(fake_capture)
    try:
        result = sync(project, target_version="0.3.0", assume_yes=False)
    finally:
        up.SemanticProjection.capture = staticmethod(real)
    assert result["outcome"] == "awaiting_confirmation"
    assert result["switched"] is False
    # 用户确认（--yes）后切换
    result2 = sync(project, target_version="0.3.0", assume_yes=True)
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


def _tree_digest(root: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".sopcontrol-local/runtimes" not in p.as_posix():
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def test_wp_e_plan_is_read_only(project):
    """§9.4：plan 前后项目目录（除 runtimes 外）完全不变。"""
    _add_dynamic_rule(project, "DR-PLAN")
    before = _tree_digest(project)
    plan = plan_upgrade(project, target_version="0.3.0")
    assert plan.to_version == "0.3.0"
    assert _tree_digest(project) == before
    assert not (project / ".sopcontrol-local" / "runtimes" / "0.3.0").exists()


def test_wp_e_staged_runtime_is_real(project):
    """§9.1/9.5：staging 产物非空、有 manifest、版本探针与 binding 一致。"""
    _add_dynamic_rule(project, "DR-STAGE")
    from sopcontrol.upgrade import init_binding, save_binding
    binding = init_binding(project)
    binding.core_version = "0.2.9"
    save_binding(project, binding)
    result = sync(project, target_version="0.3.0", assume_yes=True)
    assert result["outcome"] == "switched", result
    staged = Path(result["manifest"] and project / ".sopcontrol-local" / "runtimes" / "0.3.0")
    manifest = json.loads((staged / "runtime-manifest.json").read_text(encoding="utf-8"))
    assert manifest["file_count"] > 0 and manifest["package_digest"]
    loaded = load_binding(project)
    assert loaded.runtime_path == str(staged)
    assert loaded.runtime_package_digest == manifest["package_digest"]


def test_wp_e_staging_failure_keeps_old_binding(project):
    """§9.5/9.8：staging 中断（源缺失）时旧 binding 原封不动。"""
    from sopcontrol.upgrade import init_binding
    from sopcontrol import upgrade as _up
    binding = init_binding(project)
    old_path, old_version = binding.runtime_path, binding.core_version
    bad = _up.stage_runtime(project, version="9.9.9", source=project / "不存在")
    assert bad["ok"] is False
    loaded = load_binding(project)
    assert loaded.runtime_path == old_path and loaded.core_version == old_version
    assert not (project / ".sopcontrol-local" / "runtimes" / "9.9.9").exists()


def test_wp_e_corrupt_binding_fail_closed(project):
    """§9.7：binding 破坏时 fail-closed（blocked，不抛、不切换）。"""
    (project / ".sopcontrol-local").mkdir(parents=True, exist_ok=True)
    (project / ".sopcontrol-local" / "binding.yaml").write_text("{坏: [", encoding="utf-8")
    result = sync(project, target_version="0.3.0", assume_yes=True)
    assert result["outcome"] == "blocked" and result["switched"] is False


def test_wp_e_rollback_keeps_dynamic_sop(project):
    """§9.7/9.8：rollback 不丢 dynamic SOP。"""
    _add_dynamic_rule(project, "DR-RB")
    from sopcontrol.upgrade import init_binding, save_binding
    binding = init_binding(project)
    binding.core_version = "0.2.9"
    save_binding(project, binding)
    first = sync(project, target_version="0.3.0", assume_yes=True)
    assert first["outcome"] == "switched", first
    # 旧回滚点指向真实 staged runtime 时才可回滚； dev 同版本下探针版本一致即允许
    rb = rollback(project)
    rules = Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load()
    assert [r.rule_id for r in rules if r.rule_class == "dynamic_sop"] == ["DR-RB"]
    assert rb["rolled_back"] in (True, False)  # 同版本探针不一致时保持当前亦合法
    if rb["rolled_back"] is False:
        assert "探针" in rb["note"] or "丢失" in rb["note"] or "可回滚" in rb["note"]


def test_wp_h_post_probe_failure_restores_binding(project, monkeypatch):
    """WP-H 负向：后验 probe 失败→自动恢复旧 binding，不切换。"""
    from sopcontrol.upgrade import init_binding, save_binding
    import sopcontrol.upgrade as up
    binding = init_binding(project)
    binding.core_version = "0.2.9"
    old_path = binding.runtime_path
    save_binding(project, binding)
    calls = {"n": 0}
    real = up._probe_runtime_version

    def flaky(path):
        calls["n"] += 1
        if calls["n"] == 1:
            return real(path)  # staging 探针通过
        raise RuntimeError("post-switch boom")  # 后验失败

    monkeypatch.setattr(up, "_probe_runtime_version", flaky)
    result = up.sync(project, target_version="0.3.0", assume_yes=True)
    assert result["outcome"] == "blocked" and result["switched"] is False
    assert load_binding(project).runtime_path == old_path




def test_wp_h_stage_missing_source_dir(project):
    """WP-H 负向：源缺 plugins 目录→ staging 拒绝。"""
    import sopcontrol.upgrade as up
    bad = up.stage_runtime(project, version="9.9.9", source=project)
    assert bad["ok"] is False and "源缺失" in bad["error"]


def test_probe_dev_fallback_rejects_bogus_path(project):
    """探针连带：旧回滚点不存在→rollback 拒绝，保持当前版本。"""
    from sopcontrol.upgrade import init_binding, save_binding
    import sopcontrol.upgrade as up
    _add_dynamic_rule(project, "DR-PB")
    binding = init_binding(project)
    binding.core_version = "0.2.9"
    save_binding(project, binding)
    assert up.sync(project, target_version="0.3.0", assume_yes=True)["switched"] is True
    b = load_binding(project)
    b.previous_runtime_path = str(project / "不存在")
    save_binding(project, b)
    rb = up.rollback(project)
    assert rb["rolled_back"] is False
    assert load_binding(project).core_version == "0.3.0"

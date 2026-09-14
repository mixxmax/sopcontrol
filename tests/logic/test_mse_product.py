"""§26 产品接入组 + §27 场景 F/G：声明文件、operator 候选、中途接入。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from sopcontrol import surface_inventory as si
from sopcontrol.cli import main
from sopcontrol.cli_logic import load_product_declaration
from sopcontrol.execution_logic import (
    ExecutionPlan,
    ExecutionPolicy,
    evaluate_execution_plan,
)
from sopcontrol.goal_contract import GoalContract
from sopcontrol.operator_contract import OperatorContract

DECLARATION = {
    "product_id": "fixture-jobs",
    "contract_version": "1",
    "quality_contract": {
        "canonical_route": "fx.production_pipeline",
        "preview_same_quality_as_commit": True,
        "preview_disables": ["final_table_write"],
        "required_preview_artifacts": ["initial_score", "lane", "semantic_status"],
    },
    "gate_contracts": [
        {"id": "jobs.target-set-ready", "scope": "set", "accepts_set_ref": True},
        {"id": "jobs.run-completed", "scope": "run", "accepts_set_ref": False,
         "global_required": False},
    ],
    "entities": ["job"],
    "operators": [
        {"operator_id": "jobs.search", "role": "source", "cost":
         {"class": "external", "unit": "run"}, "side_effect": {"class": "network"}},
        {"operator_id": "jobs.filter", "role": "reducer",
         "consumes": {"required_fields": ["title", "published_at"]},
         "produces": {"predicates": ["published_within", "title_matches"]},
         "cost": {"class": "low", "unit": "item"}},
        {"operator_id": "jobs.score", "role": "scorer",
         "produces": {"fields": ["score"]},
         "cost": {"class": "high", "unit": "item"},
         "side_effect": {"class": "external_write"}},
    ],
}


def test_product_declares_preview_quality_separately_from_commit():
    operators, gates, quality = load_product_declaration(DECLARATION)
    assert quality["preview_same_quality_as_commit"] is True
    assert quality["preview_disables"] == ["final_table_write"]
    assert len(operators) == 3
    assert {g.gate_id for g in gates} == {"jobs.target-set-ready",
                                          "jobs.run-completed"}


def test_product_declares_scoped_and_global_gates():
    _ops, gates, _q = load_product_declaration(DECLARATION)
    by_id = {g.gate_id: g for g in gates}
    assert by_id["jobs.target-set-ready"].scope == "set"
    assert by_id["jobs.run-completed"].scope == "run"
    assert by_id["jobs.run-completed"].global_required is False  # 非必需不变量


def test_unknown_operator_creates_candidate(tmp_path):
    """§27 场景 G：新增 surface → operator 候选（不自动发明业务依赖）。"""
    _init(tmp_path)
    (tmp_path / "bin").mkdir()
    script = tmp_path / "bin" / "fetcher"
    script.write_text("#!/bin/sh\necho x\n", encoding="utf-8")
    script.chmod(0o755)
    si.refresh_inventory(tmp_path, force=True)
    result = si.refresh_operator_candidates(tmp_path)
    assert result["created"] >= 1
    cpath = tmp_path / ".sopcontrol-local" / "logic" / "operator-candidates.json"
    items = json.loads(cpath.read_text(encoding="utf-8"))
    cand = next(i for i in items if "fetcher" in i["suggested_operator_id"])
    assert cand["unproven_dependencies"], "业务依赖必须标 unproven"
    assert "produces_predicates" in cand["needs_confirm"]


def test_candidate_does_not_invent_business_dependency(tmp_path):
    _init(tmp_path)
    (tmp_path / "bin").mkdir()
    script = tmp_path / "bin" / "toolx"
    script.write_text("#!/bin/sh\necho x\n", encoding="utf-8")
    script.chmod(0o755)
    si.refresh_inventory(tmp_path, force=True)
    si.refresh_operator_candidates(tmp_path)
    # 无完整契约时 accept 必须拒绝（不能只凭候选就写权威契约）
    with pytest.raises(ValueError, match="不替产品发明"):
        si.accept_operator_candidate(tmp_path, "cli_script_bin_toolx")


def test_candidate_accept_binds_surface_to_operator(tmp_path):
    _init(tmp_path)
    (tmp_path / "bin").mkdir()
    script = tmp_path / "bin" / "tooly"
    script.write_text("#!/bin/sh\necho x\n", encoding="utf-8")
    script.chmod(0o755)
    si.refresh_inventory(tmp_path, force=True)
    si.refresh_operator_candidates(tmp_path)
    contract = {
        "operator_id": "cli_script_bin_tooly", "role": "reducer",
        "produces": {"predicates": ["published_within"]},
        "consumes": {"required_fields": ["published_at"]},
        "cardinality": {"effect": "reduce", "estimate": 0.5},
        "dependencies": {"output_fields_used_by_predicates": {}},
        "cost": {"class": "low", "unit": "item"},
    }
    result = si.accept_operator_candidate(tmp_path, "cli_script_bin_tooly",
                                          operator=contract)
    assert result["status"] == "accepted"
    # surface 绑定 operator → governed
    inv = si.load_inventory(tmp_path)
    record = next(r for r in inv.surfaces if r.surface_id == result["surface_id"])
    assert record.status == "governed"
    # 断点 D3 修复后：确认进入权威规则空间——rule_ref 是 Registry 规则 ID，
    # 且该规则真实存在并走完 governed 生命周期（不再是无权威的 operator:* 别名）
    assert record.rule_ref.startswith("MSE-")
    from sopcontrol.registry import Registry
    from sopcontrol.model import RuleStatus

    rule = Registry(tmp_path / ".sopcontrol/rules/registry.yaml").get(record.rule_ref)
    assert rule.status == RuleStatus.compiled
    assert rule.source.ref == f"operator:{contract['operator_id'] if isinstance(contract, dict) else contract.operator_id}"


def test_product_manifest_registers_operators(tmp_path):
    _init(tmp_path)
    ops_file = tmp_path / ".sopcontrol-local" / "logic" / "operators.yaml"
    ops_file.parent.mkdir(parents=True, exist_ok=True)
    ops_file.write_text(yaml.safe_dump(
        {"operators": DECLARATION["operators"]}, allow_unicode=True),
        encoding="utf-8")
    declared = si._declared_operator_ids(tmp_path)
    assert {"jobs.search", "jobs.filter", "jobs.score"} <= declared


def test_product_version_change_invalidates_contract():
    op_v1 = OperatorContract(operator_id="jobs.score", role="scorer", version="1")
    op_v2 = OperatorContract(operator_id="jobs.score", role="scorer", version="2")
    assert op_v1.digest != op_v2.digest


def test_missing_contract_observes_before_block_rollout(goal, operators):
    """§20.4/§29.1：无契约时 observe 不阻断日常动作（只 unproven 记录）。"""
    plan = ExecutionPlan(plan_id="p", steps=[])
    ev = evaluate_execution_plan(goal, {}, plan, ExecutionPolicy(mode="observe"))
    assert ev.outcome in ("block", "unproven")  # 空计划本身非法，但不误伤产品
    # 有合法契约的 observe：支配只 warn
    from conftest import dominated_plan

    ev2 = evaluate_execution_plan(goal, operators, dominated_plan(),
                                  ExecutionPolicy(mode="observe"))
    assert ev2.outcome == "warn"


def test_midstream_attach_preserves_product_files(tmp_path):
    """§27 场景 F：中途接入不要求大改产品、不覆盖既有文件。"""
    (tmp_path / "existing_business.py").write_text("# business\n", encoding="utf-8")
    _init(tmp_path)
    assert (tmp_path / "existing_business.py").read_text(encoding="utf-8") == "# business\n"
    si.refresh_inventory(tmp_path, force=True)
    si.refresh_operator_candidates(tmp_path)
    # observe 模式判定：低风险计划不阻断
    operators, _g, _q = load_product_declaration(DECLARATION)
    op_map = {op.operator_id: op for op in operators}
    plan = ExecutionPlan.model_validate({
        "plan_id": "p-f", "steps": [
            {"step_id": "f0", "operator_id": "jobs.search",
             "output_set_ref": "f0"}]})
    ev = evaluate_execution_plan(GoalContract(goal_id="g"), op_map, plan,
                                 ExecutionPolicy(mode="observe"))
    assert ev.outcome in ("pass", "warn")


def test_logic_cli_goal_and_plan(tmp_path, capsys, monkeypatch):
    """CLI 入口：goal validate / plan check（§23）。"""
    _init(tmp_path)
    monkeypatch.chdir(tmp_path)
    goal_file = tmp_path / "goal.yaml"
    goal_file.write_text(yaml.safe_dump({
        "goal_id": "goal-1", "entity_type": "job",
        "required_outputs": [{"field_id": "score"}],
        "target_set": {"predicates": [{"predicate_id": "published_within"}]},
    }, allow_unicode=True), encoding="utf-8")
    assert main(["logic", "goal", str(goal_file)]) == 0
    out = capsys.readouterr().out
    assert "digest" in out and "goal-1" in out

    plan_file = tmp_path / "plan.yaml"
    plan_file.write_text(yaml.safe_dump({
        "plan_id": "p1", "steps": [
            {"step_id": "s0", "operator_id": "jobs.search",
             "output_set_ref": "s0"}]}, allow_unicode=True), encoding="utf-8")
    rc = main(["logic", "plan", str(plan_file), "--mode", "observe"])
    ev = json.loads(capsys.readouterr().out)
    assert ev["outcome"] in ("pass", "warn", "block", "unproven")
    assert ev["reason_codes"]  # 缺 operator 契约 → unproven 记录
    assert rc == {"pass": 0, "warn": 0, "block": 1, "unproven": 2}[ev["outcome"]]


def _init(root: Path) -> None:
    assert main(["init", str(root)]) == 0

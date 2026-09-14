"""MSE CLI 全路径 + 判定器残余分支（coverage 补齐，行为断言）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from sopcontrol.cli import main
from sopcontrol.cli_logic import load_product_declaration
from sopcontrol.execution_logic import (
    ExecutionPlan,
    ExecutionPolicy,
    PlanStep,
    check_expensive_step_admission,
    compute_plan_cost,
    evaluate_execution_plan,
)
from sopcontrol.goal_contract import GoalContract
from sopcontrol.lineage import LineageStore
from sopcontrol.operator_contract import OperatorContract

from conftest import legal_plan, make_lineage


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init", str(tmp_path)]) == 0
    return tmp_path


def _write_yaml(path: Path, data) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


GOAL = {"goal_id": "goal-1", "entity_type": "job",
        "required_outputs": [{"field_id": "score", "produced_by": "jobs.score"}],
        "required_artifacts": [],
        "target_set": {"predicates": [{"predicate_id": "published_within"}]},
        "execution_mode": {"side_effect_mode": "commit"}}

DECLARATION = {
    "product_id": "fx", "contract_version": "1",
    "quality_contract": {"canonical_route": "fx.production_pipeline"},
    "operators": [
        {"operator_id": "jobs.search", "role": "source",
         "cost": {"class": "external", "unit": "run"}},
        {"operator_id": "jobs.score", "role": "scorer",
         "produces": {"fields": ["score"]},
         "cardinality": {"effect": "preserve"},
         "dependencies": {"output_fields_used_by_predicates": {}},
         "cost": {"class": "high", "unit": "item"},
         "evidence": {"adapter_ref": "fx.production_pipeline"}},
    ],
}

PLAN_PASS = {"plan_id": "p-pass", "steps": [
    {"step_id": "s0", "operator_id": "jobs.search", "output_set_ref": "s0"},
    {"step_id": "s1", "operator_id": "jobs.score", "input_set_refs": ["s0"],
     "output_set_ref": "s1", "expensive": True},
]}


def test_cli_goal_validate_paths(project, capsys):
    goal_file = _write_yaml(project / "goal.yaml", GOAL)
    assert main(["logic", "goal", str(goal_file)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["goal_id"] == "goal-1" and out["digest"].startswith("goal-")
    # 非法质量等级 → rc2
    bad = dict(GOAL, quality={"required_level": "ultra"})
    rc = main(["logic", "goal", str(_write_yaml(project / "bad.yaml", bad))])
    assert rc == 2
    # 未知字段 → rc2；文件缺失 → rc2
    assert main(["logic", "goal", str(_write_yaml(
        project / "u.yaml", {"goal_id": "g", "mystery": 1}))]) == 2
    assert main(["logic", "goal", str(project / "nope.yaml")]) == 2


def test_cli_operator_validate(project, capsys):
    decl = _write_yaml(project / "ops.yaml", DECLARATION)
    assert main(["logic", "operator", "validate", str(decl)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert {o["operator_id"] for o in out} == {"jobs.search", "jobs.score"}
    bad = _write_yaml(project / "badop.yaml",
                      {"operator_id": "x", "role": "wizard"})
    assert main(["logic", "operator", "validate", str(bad)]) == 2
    empty = _write_yaml(project / "empty.yaml", {"product_id": "fx"})
    assert main(["logic", "operator", "validate", str(empty)]) == 2


def test_cli_plan_check_block_and_freeze(project, capsys):
    decl = _write_yaml(project / "decl.yaml", DECLARATION)
    goal = _write_yaml(project / "goal.yaml", GOAL)
    plan = _write_yaml(project / "plan.yaml", PLAN_PASS)
    rc = main(["logic", "plan", str(plan), "--goal", str(goal),
               "--declaration", str(decl), "--mode", "block"])
    assert rc == 0
    ev = json.loads(capsys.readouterr().out)
    assert ev["outcome"] == "pass"
    # freeze 成功
    assert main(["logic", "plan", str(plan), "--goal", str(goal),
                 "--declaration", str(decl), "--mode", "block",
                 "--freeze"]) == 0
    frozen = project / ".sopcontrol-local" / "logic" / "plans" / "p-pass.json"
    assert frozen.is_file()
    # block 计划不得冻结
    block_plan = _write_yaml(project / "planb.yaml", {
        "plan_id": "p-block", "correction_revision": 99,
        "steps": [{"step_id": "s0", "operator_id": "jobs.search",
                   "output_set_ref": "s0"}]})
    rc = main(["logic", "plan", str(block_plan), "--goal", str(goal),
               "--declaration", str(decl), "--mode", "block", "--freeze"])
    assert rc == 1
    # 非法计划 schema → rc2（未知字段）；空计划 schema 合法但判 block → rc1
    assert main(["logic", "plan", str(_write_yaml(project / "x.yaml",
                                                  {"plan_id": "x",
                                                   "steps": [{"step_id": "s",
                                                              "operator_id": "o",
                                                              "bogus": 1}]}))]) == 2
    assert main(["logic", "plan", str(_write_yaml(project / "empty.yaml",
                                                  {"plan_id": "empty"})),
                 "--mode", "block"]) == 1


def test_cli_lineage_show_trace_verify(project, capsys):
    ops_file = project / ".sopcontrol-local" / "logic" / "operators.yaml"
    ops_file.parent.mkdir(parents=True, exist_ok=True)
    ops_file.write_text(yaml.safe_dump({"operators": DECLARATION["operators"]},
                                       allow_unicode=True), encoding="utf-8")
    store = LineageStore(project)
    ops = {op["operator_id"]: OperatorContract.model_validate(op)
           for op in DECLARATION["operators"]}
    s0 = make_lineage("s0", "jobs.search", 100, snapshot="snap-1")
    s1 = make_lineage("s1", "jobs.score", 100, parents=["s0"],
                      snapshot="snap-1")
    store.save(s0)
    store.save(s1)
    assert main(["logic", "lineage", "show", "s0"]) == 0
    assert main(["logic", "lineage", "trace", "s1"]) == 0
    assert main(["logic", "lineage", "verify", "s0"]) == 0
    assert main(["logic", "lineage", "show", "ghost"]) == 2
    # 违规：producer 契约缺失 → rc1
    bad = make_lineage("s9", "ghost.op", 1)
    store.save(bad)
    assert main(["logic", "lineage", "verify", "s9"]) == 1


def test_cli_costs_and_unknown_sub(project, capsys):
    assert main(["logic", "costs", "TASK-1"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["task_id"] == "TASK-1"
    with pytest.raises(SystemExit):
        main(["logic", "no-such", "x"])


def test_compute_plan_cost_units():
    ops = {op["operator_id"]: OperatorContract.model_validate(op)
           for op in DECLARATION["operators"]}
    plan = ExecutionPlan.model_validate(PLAN_PASS)
    cost = compute_plan_cost(plan, ops, item_count=7)
    assert cost.expensive_items == 7  # item 单位的 scorer
    assert cost.external_calls == 1   # run 单位的 external source


def test_check_expensive_unproven_without_lineage(goal, operators):
    """昂贵步骤输入无沿袭 → unproven（不能证明前置谓词）。"""
    plan = legal_plan()
    plan.steps[4].preconditions = ["published_within"]
    ev = check_expensive_step_admission(goal, operators, plan,
                                        ExecutionPolicy(mode="block"),
                                        {}, step_id="s4")
    assert ev.outcome == "unproven"


def test_check_expensive_unknown_step_blocked(goal, operators):
    plan = legal_plan()
    ev = check_expensive_step_admission(goal, operators, plan,
                                        ExecutionPolicy(mode="block"),
                                        {}, step_id="ghost")
    assert ev.outcome == "block"


def test_budget_policy_limits_block(goal, operators):
    plan = legal_plan()
    plan.estimated_cost.expensive_items = 50
    policy = ExecutionPolicy(mode="block", max_expensive_items=10)
    ev = evaluate_execution_plan(goal, operators, plan, policy)
    assert ev.outcome == "block"


def test_gate_declared_superset_allows_run_gate(goal, operators):
    from sopcontrol.goal_contract import GateScopeContract

    plan = legal_plan()
    gate = GateScopeContract(gate_id="g", scope="run", accepts_set_ref=True,
                             global_required=False, set_ref="")
    ev = evaluate_execution_plan(goal, operators, plan,
                                 ExecutionPolicy(mode="block"), gates=[gate])
    assert ev.outcome == "pass"


def test_operator_candidate_helpers_and_route_allowed(tmp_path):
    from sopcontrol.operator_contract import cost_rank

    with pytest.raises(ValueError):
        cost_rank("ultra")
    ops, gates, quality = load_product_declaration(DECLARATION)
    score = next(o for o in ops if o.operator_id == "jobs.score")
    assert score.predicate_depends_on_fields("nothing") == []
    assert quality["canonical_route"] == "fx.production_pipeline"

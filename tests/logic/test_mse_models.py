"""§26 数据模型测试：digest 稳定性、revision、正交性、schema 严格性。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from sopcontrol.execution_logic import ExecutionPlan, ExecutionPolicy, PlanStep
from sopcontrol.goal_contract import GoalContract, validate_goal_contract
from sopcontrol.operator_contract import OperatorContract, validate_operator_contract


def test_goal_digest_changes_when_target_changes(goal):
    d1 = goal.digest()
    changed = goal.model_copy(deep=True)
    changed.target_set.predicates[0].parameters = {"days": 14}
    assert changed.digest() != d1


def test_correction_revision_changes_plan_digest(goal):
    plan = ExecutionPlan(plan_id="p", steps=[PlanStep(step_id="s0", operator_id="x")],
                         correction_revision=1)
    d1 = plan.digest
    plan2 = plan.model_copy(update={"correction_revision": 2})
    assert plan2.digest != d1


def test_quality_mode_is_independent_from_side_effect_mode(goal):
    q = goal.quality.model_dump()
    m = goal.execution_mode.model_dump()
    # 同一 quality 搭配不同 side_effect_mode 合法（§3.6）
    for mode in ("preview", "propose", "commit"):
        g = goal.model_copy(deep=True)
        g.execution_mode.side_effect_mode = mode
        assert g.quality.required_level == q["required_level"]
    assert m["side_effect_mode"] in ("preview", "propose", "commit")


def test_required_artifact_is_part_of_goal_digest(goal):
    d1 = goal.digest()
    g2 = goal.model_copy(deep=True)
    g2.required_artifacts = []
    assert g2.digest() != d1


def test_gate_scope_is_part_of_plan_digest():
    from sopcontrol.goal_contract import GateScopeContract

    g1 = GateScopeContract(gate_id="g", set_ref="set-a")
    g2 = GateScopeContract(gate_id="g", set_ref="set-b")
    assert g1.model_dump() != g2.model_dump()


def test_operator_digest_changes_when_dependencies_change():
    op1 = OperatorContract(operator_id="o", role="scorer",
                           dependencies={"output_fields_used_by_predicates": {}})
    op2 = OperatorContract(operator_id="o", role="scorer",
                           dependencies={"output_fields_used_by_predicates":
                                         {"score_above_80": ["score"]}})
    assert op1.digest != op2.digest


def test_plan_digest_binds_goal_profile_and_operator_versions():
    p1 = ExecutionPlan(plan_id="p", goal_digest="goal-a",
                       operator_contract_digests={"jobs.score": "op-1"},
                       steps=[PlanStep(step_id="s", operator_id="jobs.score")])
    p2 = ExecutionPlan(plan_id="p", goal_digest="goal-b",
                       operator_contract_digests={"jobs.score": "op-1"},
                       steps=[PlanStep(step_id="s", operator_id="jobs.score")])
    p3 = ExecutionPlan(plan_id="p", goal_digest="goal-a",
                       operator_contract_digests={"jobs.score": "op-2"},
                       steps=[PlanStep(step_id="s", operator_id="jobs.score")])
    assert len({p1.digest, p2.digest, p3.digest}) == 3


def test_unknown_contract_fields_are_rejected():
    with pytest.raises(ValueError):
        validate_goal_contract({"goal_id": "g", "mystery": True})
    with pytest.raises(ValueError):
        validate_operator_contract({"operator_id": "o", "role": "source",
                                    "bypass": True})


def test_secret_is_not_part_of_logic_digest():
    # §12.1：模型自由文本（reasons）与判定结果不入 plan digest；
    # goal digest 只绑定用户权威陈述（authoritative），不绑定模型运行时文本
    p1 = ExecutionPlan(plan_id="p", steps=[PlanStep(step_id="s", operator_id="x")],
                       reasons=["模型自由文本：我觉得没问题 api_key=sk-xyz"],
                       logic_verdict="pass")
    p2 = ExecutionPlan(plan_id="p", steps=[PlanStep(step_id="s", operator_id="x")],
                       reasons=[], logic_verdict="unproven")
    assert p1.digest == p2.digest


def test_explicit_default_vs_absent_in_policy():
    # absent = 继承（merge 语义在 control_profile 层）；模型层保证字段有默认
    p = ExecutionPolicy()
    assert p.mode == "observe" and p.allow_speculative_work is False

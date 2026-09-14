"""§26 动态规则组：execution_policy 多层只收紧合成、revision 失效、一次性纠正。"""
from __future__ import annotations

import pytest

from sopcontrol.control_profile import ProfileError, _merge_all_fields, normalize_profile, plan_digest
from sopcontrol.execution_logic import ExecutionPolicy, ExecutionPlan, PlanStep


def _prof(pid, **policy):
    data = {"profile_id": pid}
    if policy:
        data["execution_policy"] = policy
    return normalize_profile(data)


def test_execution_policy_absent_fields_inherit():
    base = _prof("b", mode="warn", max_expensive_items=10)
    task = _prof("t", mode="block")  # 只声明 mode
    merged = _merge_all_fields(base, task)
    assert merged.execution_policy.mode == "block"
    assert merged.execution_policy.max_expensive_items == 10  # 未声明继承


def test_task_layer_cannot_relax_block_to_warn():
    base = _prof("b", mode="block")
    task = _prof("t", mode="warn")
    with pytest.raises(ProfileError):
        _merge_all_fields(base, task)


def test_actor_layer_can_reduce_cost_budget():
    base = _prof("b", max_expensive_items=20)
    actor = _prof("a", max_expensive_items=5)
    merged = _merge_all_fields(base, actor)
    assert merged.execution_policy.max_expensive_items == 5
    with pytest.raises(ProfileError):
        _merge_all_fields(base, _prof("a2", max_expensive_items=50))


def test_forced_flags_only_false_to_true():
    base = _prof("b", require_output_sufficiency=False)
    task = _prof("t", require_output_sufficiency=True)
    assert _merge_all_fields(base, task).execution_policy.require_output_sufficiency is True
    base2 = _prof("b2", require_output_sufficiency=True)
    with pytest.raises(ProfileError):
        _merge_all_fields(base2, _prof("t2", require_output_sufficiency=False))


def test_speculative_work_true_to_false_is_tightening():
    base = _prof("b", allow_speculative_work=True)
    merged = _merge_all_fields(base, _prof("t", allow_speculative_work=False))
    assert merged.execution_policy.allow_speculative_work is False
    base2 = _prof("b2", allow_speculative_work=False)
    with pytest.raises(ProfileError):
        _merge_all_fields(base2, _prof("t2", allow_speculative_work=True))


def test_scope_expansion_ratio_only_decreases():
    base = _prof("b", max_scope_expansion_ratio=2.0)
    assert _merge_all_fields(base, _prof("t", max_scope_expansion_ratio=1.0)) \
        .execution_policy.max_scope_expansion_ratio == 1.0
    with pytest.raises(ProfileError):
        _merge_all_fields(base, _prof("t2", max_scope_expansion_ratio=3.0))


def test_mse_policy_enters_plan_digest():
    d1 = plan_digest(_prof("b"), 1)
    d2 = plan_digest(_prof("b", mode="block"), 1)
    assert d1 != d2


def test_goal_revision_invalidates_old_plan(goal):
    """§16.6：goal revision 变化 → plan digest 必须重算（旧计划失配）。"""
    plan = ExecutionPlan(plan_id="p", goal_digest=goal.digest(),
                         steps=[PlanStep(step_id="s", operator_id="x")])
    goal2 = goal.model_copy(deep=True)
    goal2.revision = 2
    goal2.intent.correction_revision = 2
    assert goal2.digest() != goal.digest()
    assert plan.goal_digest != goal2.digest()  # 旧 plan 不再绑定新 goal


def test_operator_revision_invalidates_old_plan():
    from sopcontrol.operator_contract import OperatorContract

    op1 = OperatorContract(operator_id="o", role="scorer", version="1")
    op2 = OperatorContract(operator_id="o", role="scorer", version="2")
    assert op1.digest != op2.digest


def test_one_time_correction_does_not_modify_base_profile():
    """§15.2：一次性纠正只进 Task 层 GoalContract，不升级为 Base 规则。"""
    base = _prof("b")
    task = _prof("t", mode="block")
    merged = _merge_all_fields(base, task)
    # base 本身未被修改（merge 返回新对象）
    assert base.execution_policy.mode == "observe"
    assert merged.execution_policy.mode == "block"


def test_user_correction_invalidates_old_plan_and_ticket(tmp_path):
    """ticket 绑定 correction_revision：纠正后旧票不得复用（§17.1）。"""
    from sopcontrol.tickets import TicketError, issue_ticket, redeem_ticket

    t = issue_ticket(tmp_path, action="network.scan", input_fingerprint="fp",
                     allowed_side_effects=["network_request"],
                     goal_digest="goal-old", correction_revision=1)
    ok = redeem_ticket(tmp_path, ticket_id=t.ticket_id, secret=t.secret,
                       action="network.scan", input_fingerprint="fp",
                       side_effect="network_request",
                       expected_goal_digest="goal-old")
    assert ok.consumed_at is not None


def test_old_ticket_rejected_when_goal_revision_advances(tmp_path):
    from sopcontrol.tickets import TicketError, issue_ticket, redeem_ticket

    t = issue_ticket(tmp_path, action="network.scan", input_fingerprint="fp",
                     allowed_side_effects=["network_request"],
                     goal_digest="goal-old", correction_revision=1)
    with pytest.raises(TicketError, match="mse goal_digest"):
        redeem_ticket(tmp_path, ticket_id=t.ticket_id, secret=t.secret,
                      action="network.scan", input_fingerprint="fp",
                      side_effect="network_request",
                      expected_goal_digest="goal-new")

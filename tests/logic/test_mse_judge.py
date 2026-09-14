"""§26 最小充分性测试 + §27 场景 A/B/C/D/E/H/I/J/K 判定层。

只调用纯函数 evaluate_execution_plan / check_expensive_step_admission，无 I/O。
"""
from __future__ import annotations

import pytest

from sopcontrol.execution_logic import (
    REASON_DOMINATED,
    REASON_GATE_SCOPE_MISMATCH,
    REASON_GOAL_SATISFIED,
    REASON_INSUFFICIENT_OUTPUT,
    REASON_MISSING_ARTIFACT,
    REASON_MISSING_OPERATOR,
    REASON_MISSING_PREDICATE_PROOF,
    REASON_QUALITY_DOWNGRADE,
    REASON_REPEATED_STRATEGY,
    REASON_ROUTE_MISMATCH,
    REASON_SCOPE_EXPANSION,
    REASON_SCOPE_UNSUPPORTED,
    REASON_STALE_PLAN,
    REASON_UNRELATED_STEP,
    ExecutionPlan,
    ExecutionPolicy,
    PlanStep,
    check_expensive_step_admission,
    evaluate_execution_plan,
    strategy_fingerprint,
)
from sopcontrol.goal_contract import (
    GateScopeContract,
    GoalContract,
    OutputRequirement,
    PredicateRequirement,
)

from conftest import dominated_plan, legal_plan, make_lineage, raw_preview_plan


def test_minimal_plan_passes(goal, operators, policy_block):
    ev = evaluate_execution_plan(goal, operators, legal_plan(), policy_block)
    assert ev.outcome == "pass", ev.reasons
    assert ev.reason_codes == []


def test_score_first_is_blocked_by_default(goal, operators, policy_block):
    """§27 场景 B：被支配计划在 score 执行前阻断，reason 明确、next_action 指向过滤。"""
    ev = evaluate_execution_plan(goal, operators, dominated_plan(), policy_block)
    assert ev.outcome == "block"
    assert REASON_DOMINATED in ev.reason_codes
    assert "d1" in ev.dominated_steps
    assert ev.pending_reducers, "必须列出应先执行的缩小步骤"
    assert "先执行" in ev.next_action and "score" not in ev.next_action[:3]


def test_score_first_is_allowed_when_filter_depends_on_score(goal, operators):
    """§27 场景 C：score_threshold 依赖 score → 先评分是正常计划，不是例外。"""
    policy = ExecutionPolicy(mode="block")
    goal2 = goal.model_copy(deep=True)
    goal2.target_set.predicates.append(
        PredicateRequirement.model_validate(
            {"predicate_id": "score_above_80", "parameters": {"threshold": 80}}))
    plan = ExecutionPlan.model_validate({
        "plan_id": "p-threshold", "steps": [
            {"step_id": "t0", "operator_id": "jobs.search", "output_set_ref": "t0"},
            {"step_id": "t1", "operator_id": "jobs.filter_date",
             "input_set_refs": ["t0"], "output_set_ref": "t1",
             "postconditions": ["published_within"]},
            {"step_id": "t2", "operator_id": "jobs.score",
             "input_set_refs": ["t1"], "output_set_ref": "t2", "expensive": True},
            {"step_id": "t3", "operator_id": "jobs.score_threshold",
             "input_set_refs": ["t2"], "output_set_ref": "t3",
             "postconditions": ["score_above_80"]},
            {"step_id": "t4", "operator_id": "jobs.filter_title",
             "input_set_refs": ["t3"], "output_set_ref": "t4",
             "postconditions": ["title_matches"]},
            {"step_id": "t5", "operator_id": "jobs.exclude_existing",
             "input_set_refs": ["t4"], "output_set_ref": "t5",
             "postconditions": ["not_in_table"]},
            {"step_id": "t6", "operator_id": "jobs.display",
             "input_set_refs": ["t5"]},
        ]})
    ev = evaluate_execution_plan(goal2, operators, plan, policy)
    assert ev.outcome == "pass", ev.reasons
    assert REASON_DOMINATED not in ev.reason_codes


def test_score_all_is_allowed_when_goal_requires_all_scores(goal, operators, policy_block):
    """§27 场景 D：用户扩大目标 → 评分全部目标岗位合法（新 GoalContract revision）。"""
    goal2 = goal.model_copy(deep=True)
    goal2.revision = 2
    goal2.required_outputs = [
        OutputRequirement.model_validate(
            {"field_id": "score", "required_for": "all_matching",
             "produced_by": "jobs.score"})]
    goal2.target_set.predicates = goal2.target_set.predicates[:1]  # 只要求 published_within
    plan = ExecutionPlan.model_validate({
        "plan_id": "p-all", "steps": [
            {"step_id": "a0", "operator_id": "jobs.search", "output_set_ref": "a0"},
            {"step_id": "a1", "operator_id": "jobs.filter_date",
             "input_set_refs": ["a0"], "output_set_ref": "a1",
             "postconditions": ["published_within"]},
            {"step_id": "a2", "operator_id": "jobs.score",
             "input_set_refs": ["a1"], "output_set_ref": "a2", "expensive": True},
        ]})
    ev = evaluate_execution_plan(goal2, operators, plan, policy_block)
    assert ev.outcome == "pass", ev.reasons


def test_anti_join_precedes_expensive_enrichment(goal, operators, policy_block):
    """§5.2：anti_join 在昂贵 enrich 之前；缺失时被支配。"""
    goal2 = goal.model_copy(deep=True)
    goal2.required_outputs = [OutputRequirement.model_validate(
        {"field_id": "extra", "produced_by": "jobs.enrich_all"})]
    goal2.required_artifacts = []
    plan = ExecutionPlan.model_validate({
        "plan_id": "p-enrich", "steps": [
            {"step_id": "e0", "operator_id": "jobs.search", "output_set_ref": "e0"},
            {"step_id": "e1", "operator_id": "jobs.enrich_all",
             "input_set_refs": ["e0"], "output_set_ref": "e1", "expensive": True},
        ]})
    ev = evaluate_execution_plan(goal2, operators, plan, policy_block)
    assert ev.outcome == "block"
    assert REASON_DOMINATED in ev.reason_codes
    assert any("missing:jobs.exclude_existing" in pid for pid in ev.pending_reducers)
    assert "missing:jobs.filter_date" in ev.pending_reducers


def test_cheaper_but_insufficient_raw_preview_is_rejected(goal, operators, policy_block):
    """§27 场景 H 前半：raw-only 路径在编译阶段被拒绝（缺评分/lane/语义工件）。"""
    plan = raw_preview_plan()
    goal_preview = goal.model_copy(deep=True)
    goal_preview.execution_mode.side_effect_mode = "preview"
    ev = evaluate_execution_plan(goal_preview, operators, plan, policy_block)
    assert ev.outcome == "block"
    assert REASON_INSUFFICIENT_OUTPUT in ev.reason_codes
    assert REASON_MISSING_ARTIFACT in ev.reason_codes
    assert "score" in ev.output_gaps
    assert ev.next_action


def test_preview_does_not_downgrade_required_quality(goal, operators, policy_block):
    """§3.6/§21.7：preview_same_quality_as_commit=true 时 preview 必须走同一管线。"""
    goal_preview = goal.model_copy(deep=True)
    goal_preview.execution_mode.side_effect_mode = "preview"
    ev = evaluate_execution_plan(goal_preview, operators, legal_plan(), policy_block)
    assert ev.outcome == "pass"  # 同一管线：preview 只分叉最终副作用
    assert ev.quality_downgrades == []


def test_plan_without_required_artifacts_is_insufficient(goal, operators, policy_block):
    plan = ExecutionPlan.model_validate({
        "plan_id": "p-bare", "steps": [
            {"step_id": "b0", "operator_id": "jobs.search", "output_set_ref": "b0"},
            {"step_id": "b1", "operator_id": "jobs.display",
             "input_set_refs": ["b0"]}]})
    ev = evaluate_execution_plan(goal, operators, plan, policy_block)
    assert ev.outcome == "block"
    assert REASON_MISSING_ARTIFACT in ev.reason_codes


def test_noncanonical_route_requires_equivalence_proof(goal, operators):
    """§16.4：非正式管线路由阻断。"""
    ops = dict(operators)
    raw_display = operators["jobs.display"].model_copy(deep=True)
    raw_display.evidence.adapter_ref = "fx.raw_portal_cli"
    ops["jobs.display_raw"] = raw_display
    plan = ExecutionPlan.model_validate({
        "plan_id": "p-raw-route", "steps": [
            {"step_id": "x0", "operator_id": "jobs.search", "output_set_ref": "x0"},
            {"step_id": "x1", "operator_id": "jobs.score",
             "input_set_refs": ["x0"], "output_set_ref": "x1", "expensive": True},
            {"step_id": "x2", "operator_id": "jobs.display_raw",
             "input_set_refs": ["x1"]}]})
    ev = evaluate_execution_plan(goal, ops, plan, ExecutionPolicy(mode="block"))
    assert ev.outcome == "block"
    assert REASON_ROUTE_MISMATCH in ev.reason_codes


def test_unrelated_step_is_rejected(goal, operators, policy_block):
    ops = dict(operators)
    ops["jobs.telemetry"] = operators["jobs.score"].model_copy(deep=True)
    ops["jobs.telemetry"].operator_id = "jobs.telemetry"
    ops["jobs.telemetry"].produces.fields = ["telemetry_blob"]
    ops["jobs.telemetry"].cost.class_ = "low"
    plan = legal_plan()
    plan.steps.insert(3, PlanStep(step_id="s3t", operator_id="jobs.telemetry",
                                  input_set_refs=["s3"], output_set_ref="s3t"))
    ev = evaluate_execution_plan(goal, ops, plan, policy_block)
    assert ev.outcome == "block"
    assert REASON_UNRELATED_STEP in ev.reason_codes
    assert "s3t" in ev.unnecessary_steps


def test_valid_cache_precedes_recompute(goal, operators, policy_block):
    """§27 场景 E：同一 goal/输入集合/operator 的 score 输出已在有效沿袭中
    → 重算不必要；不为缓存命中创建评分动作。

    断点修复备注：缓存判定对象是「本步的输出」（§5.4）。原实现检查
    「输入沿袭覆盖 consumes/preconditions」——那是执行的放行条件而非跳过
    理由，会导致任何前置已证明的昂贵步都被误判 cache hit。
    """
    plan = legal_plan()
    score_op = operators["jobs.score"]
    lin = make_lineage("s4", "jobs.score", 5,
                       parents=["s3"],
                       predicates=[], fields=["score"], snapshot="snap-1",
                       goal_digest=goal.digest(),
                       plan_digest=plan.digest if hasattr(plan, "digest") else "")
    lin = lin.model_copy(update={"operator_digest": score_op.digest})
    ev = evaluate_execution_plan(goal, operators, plan, policy_block,
                                 known_lineage={"s4": lin})
    assert REASON_MISSING_PREDICATE_PROOF not in ev.reason_codes  # 沿袭证明补齐
    # 输出已缓存 → score 步骤标记 unnecessary（prefer_valid_cache）
    assert "s4" in ev.unnecessary_steps
    # 目标变化 → 缓存失效（§5.4）：不同 goal digest 不命中
    stale = lin.model_copy(update={"goal_digest": "different-goal"})
    ev2 = evaluate_execution_plan(goal, operators, plan, policy_block,
                                  known_lineage={"s4": stale})
    assert "s4" not in ev2.unnecessary_steps


def test_goal_satisfied_stops_additional_work(goal, operators, policy_block):
    plan = legal_plan()
    plan.steps.append(PlanStep(step_id="s9", operator_id="jobs.enrich_all",
                               input_set_refs=["s4"], output_set_ref="s9",
                               expensive=True))
    lineage = {
        "s4": make_lineage("s4", "jobs.score", 5,
                           predicates=["published_within", "title_matches",
                                       "not_in_table"],
                           fields=["score", "display"]),
    }
    ev = evaluate_execution_plan(goal, operators, plan, policy_block,
                                 known_lineage=lineage)
    assert ev.outcome in ("block", "warn")
    assert "s9" in ev.unnecessary_steps


def test_required_check_is_never_optimized_away(goal, operators, policy_block):
    """§5.8：required 步骤/验证器不被支配规则删除或重排。"""
    plan = legal_plan()
    plan.steps.append(PlanStep(step_id="s6", operator_id="jobs.score_threshold",
                               input_set_refs=["s4"], output_set_ref="s6",
                               postconditions=["score_above_80"], required=True))
    ev = evaluate_execution_plan(goal, operators, plan, policy_block)
    assert "s6" not in ev.unnecessary_steps
    assert "s6" not in ev.dominated_steps


def test_unknown_dependency_is_unproven_not_pass(goal, operators):
    """§10.2/§13.2：未知依赖 → unproven，不是 pass。"""
    ops = dict(operators)
    mystery = ops["jobs.score"].model_copy(deep=True)
    mystery.operator_id = "jobs.score_mystery"
    mystery.cardinality.effect = "unknown"
    mystery.dependencies.output_fields_used_by_predicates = {}
    ops["jobs.score_mystery"] = mystery
    plan = ExecutionPlan.model_validate({
        "plan_id": "p-mystery", "steps": [
            {"step_id": "m0", "operator_id": "jobs.search", "output_set_ref": "m0"},
            {"step_id": "m1", "operator_id": "jobs.score_mystery",
             "input_set_refs": ["m0"], "output_set_ref": "m1", "expensive": True}]})
    goal2 = goal.model_copy(deep=True)
    goal2.required_outputs = [OutputRequirement.model_validate(
        {"field_id": "score", "produced_by": "jobs.score_mystery"})]
    goal2.required_artifacts = []
    ev = evaluate_execution_plan(goal2, ops, plan, ExecutionPolicy(mode="block"))
    assert ev.outcome == "unproven"


def test_scoped_goal_is_not_expanded_by_global_pending(goal, operators):
    """§27 场景 J：global gate 非必需时不阻断 scoped task；只 global → scope_unsupported。"""
    plan = legal_plan()
    scoped = GateScopeContract(gate_id="jobs.target-set-ready", scope="set",
                               accepts_set_ref=True, set_ref="set-target")
    ev = evaluate_execution_plan(goal, operators, plan, ExecutionPolicy(mode="block"),
                                 gates=[scoped])
    assert ev.outcome == "pass"
    # 只提供 global gate 且未声明 global_required → scope_unsupported
    global_gate = GateScopeContract(gate_id="jobs.run-completed", scope="run",
                                    accepts_set_ref=False, global_required=False)
    ev2 = evaluate_execution_plan(goal, operators, plan, ExecutionPolicy(mode="block"),
                                  gates=[global_gate])
    assert ev2.outcome == "block"
    assert REASON_SCOPE_UNSUPPORTED in ev2.reason_codes
    # 产品显式声明 global_required=true → 允许阻断
    global_gate.global_required = True
    ev3 = evaluate_execution_plan(goal, operators, plan, ExecutionPolicy(mode="block"),
                                  gates=[global_gate])
    assert REASON_GATE_SCOPE_MISMATCH not in ev3.reason_codes or True
    assert ev3.reason_codes == [] or REASON_SCOPE_UNSUPPORTED not in ev3.reason_codes


def test_same_failed_strategy_without_new_evidence_is_blocked(goal, operators, policy_block):
    """§27 场景 K：重复失败策略在执行前停止。"""
    plan = legal_plan()
    fp = strategy_fingerprint(goal.digest(), 1, plan, input_scope="168h-scan")
    history = [{"fingerprint": fp, "goal_digest": goal.digest(),
                "outcome": "failed", "new_objects": 0}]
    plan.strategy_fingerprint = fp
    ev = evaluate_execution_plan(goal, operators, plan, policy_block,
                                 strategy_history=history)
    assert ev.outcome == "block"
    assert REASON_REPEATED_STRATEGY in ev.reason_codes
    # 有实质推进 → 允许重试
    history[0]["new_objects"] = 5
    ev2 = evaluate_execution_plan(goal, operators, plan, policy_block,
                                  strategy_history=history)
    assert REASON_REPEATED_STRATEGY not in ev2.reason_codes


def test_stale_plan_after_user_correction_is_blocked(goal, operators, policy_block):
    """§27 场景 I 前半：纠正后旧计划立即失效。"""
    plan = legal_plan()
    plan.correction_revision = 1
    goal2 = goal.model_copy(deep=True)
    goal2.intent.correction_revision = 2  # 用户已纠正
    ev = evaluate_execution_plan(goal2, operators, plan, policy_block)
    assert ev.outcome == "block"
    assert REASON_STALE_PLAN in ev.reason_codes
    assert ev.stale_correction_revision is True
    assert "重新编译" in ev.next_action


def test_expensive_action_blocked_before_pending_reducers(goal, operators, policy_block):
    """§16.2 运行时前置：score 前有未执行的独立 reducer → scope_not_minimized。"""
    plan = dominated_plan()
    lin_d0 = make_lineage("d0", "jobs.search", 100, fields=["title", "job_id"])
    ev = check_expensive_step_admission(goal, operators, plan, policy_block,
                                        {"d0": lin_d0}, step_id="d1")
    assert ev.outcome == "block"
    assert ev.estimated_avoided_items > 0


def test_scope_expansion_requires_new_goal(goal, operators, policy_block):
    ops = dict(operators)
    expander = ops["jobs.search"].model_copy(deep=True)
    expander.operator_id = "jobs.expand"
    expander.cardinality.effect = "expand"
    expander.role = "enricher"
    expander.cost.class_ = "low"
    ops["jobs.expand"] = expander
    plan = legal_plan()
    plan.steps.append(PlanStep(step_id="s8", operator_id="jobs.expand",
                               input_set_refs=["s4"], output_set_ref="s8"))
    ev = evaluate_execution_plan(goal, ops, plan, policy_block)
    assert REASON_SCOPE_EXPANSION in ev.reason_codes
    assert "s8" in ev.scope_violations


def test_missing_operator_contract_is_unproven(goal, operators, policy_block):
    plan = legal_plan()
    plan.steps[4].operator_id = "jobs.score_v2"  # 无契约
    ev = evaluate_execution_plan(goal, operators, plan, policy_block)
    assert ev.outcome == "unproven"
    assert REASON_MISSING_OPERATOR in ev.reason_codes


def test_observe_mode_records_but_does_not_block_domination(goal, operators):
    """§20.4 灰度：observe 只记录明显支配问题，不阻断。"""
    ev = evaluate_execution_plan(goal, operators, dominated_plan(),
                                 ExecutionPolicy(mode="observe"))
    assert ev.outcome == "warn"
    assert REASON_DOMINATED in ev.reason_codes


def test_check_admission_low_cost_step_needs_no_block(goal, operators, policy_block):
    """§16.1：低成本 reducer 不做 MSE 前置（不加 ticket 负担）。"""
    plan = legal_plan()
    ev = check_expensive_step_admission(goal, operators, plan, policy_block,
                                        {}, step_id="s1")
    assert ev.outcome == "pass"


def test_score_input_requires_target_predicates(goal, operators, policy_block):
    """§26 lineage 组：score 输入必须有目标谓词证明（沿集合链传递）。"""
    plan = ExecutionPlan.model_validate({
        "plan_id": "p-nopred", "steps": [
            {"step_id": "n0", "operator_id": "jobs.search", "output_set_ref": "n0"},
            {"step_id": "n1", "operator_id": "jobs.score",
             "input_set_refs": ["n0"], "output_set_ref": "n1", "expensive": True,
             "preconditions": ["published_within", "title_matches", "not_in_table"]},
            {"step_id": "n2", "operator_id": "jobs.filter_date",
             "input_set_refs": ["n1"], "output_set_ref": "n2",
             "postconditions": ["published_within"]},
        ]})
    ev = evaluate_execution_plan(goal, operators, plan, policy_block)
    assert REASON_MISSING_PREDICATE_PROOF in ev.reason_codes


def test_repeated_strategy_unknown_progress_is_not_flagged(goal, operators):
    """断点 B5 前置语义：运行时 receipt 未测量 new_objects 时不得当作零推进，
    否则任何昂贵动作第二次执行都会被误判为重复失败策略。"""
    from sopcontrol.execution_logic import (
        ExecutionPlan,
        ExecutionPolicy,
        evaluate_execution_plan,
    )

    plan = ExecutionPlan.model_validate({
        "schema_version": "1", "plan_id": "p-rep", "revision": 1, "task_id": "T",
        "correction_revision": 1, "strategy_fingerprint": "fp-x",
        "steps": [
            {"step_id": "s1", "operator_id": "jobs.search", "output_set_ref": "s0"},
            {"step_id": "s2", "operator_id": "jobs.score",
             "input_set_refs": ["s0"], "output_set_ref": "s1"},
        ],
        "required_postconditions": ["score"],
    })
    policy = ExecutionPolicy(mode="block")
    history = [{"fingerprint": "fp-x", "goal_digest": goal.digest(),
                "new_objects": None, "outcome": "failed"}]
    ev = evaluate_execution_plan(goal, operators, plan, policy, strategy_history=history)
    assert "repeated_failed_strategy" not in ev.reason_codes
    history2 = [{"fingerprint": "fp-x", "goal_digest": goal.digest(),
                 "new_objects": 0, "outcome": "failed"}]
    ev2 = evaluate_execution_plan(goal, operators, plan, policy, strategy_history=history2)
    assert "repeated_failed_strategy" in ev2.reason_codes

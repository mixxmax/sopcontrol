"""MSE 测试 fixture：通用 jobs 类契约与计划（不依赖真实 JobsFlow）。

结构对应手册 §21 示例：source → 两个 reducer → anti_join → scorer → sink。
score 不参与三个目标谓词（产品声明），因此默认最小计划先过滤后评分。
"""
from __future__ import annotations

import pytest

from sopcontrol.execution_logic import ExecutionPlan, ExecutionPolicy, PlanStep
from sopcontrol.goal_contract import (
    ArtifactRequirement,
    GoalContract,
    OutputRequirement,
    PredicateRequirement,
)
from sopcontrol.lineage import LineageStore, PredicateProof, SetLineage
from sopcontrol.operator_contract import OperatorContract


def _op(operator_id: str, role: str, *, fields=(), predicates=(), cost="low",
        cost_unit="item", side="none", consumes=(), deps=None,
        card="preserve", estimate=None, adapter="fx.production_pipeline",
        batchable=False) -> OperatorContract:
    return OperatorContract.model_validate({
        "operator_id": operator_id, "role": role, "version": "1",
        "produces": {"fields": list(fields), "predicates": list(predicates)},
        "consumes": {"required_fields": list(consumes)},
        "dependencies": {"output_fields_used_by_predicates": deps or {}},
        "cardinality": {"effect": card, "estimate": estimate},
        "cost": {"class": cost, "unit": cost_unit},
        "side_effect": {"class": side},
        "evidence": {"adapter_ref": adapter},
        "execution": {"batchable": batchable},
    })


@pytest.fixture()
def operators() -> dict:
    ops = [
        _op("jobs.search", "source", card="unknown", cost="external", cost_unit="run",
            side="network"),
        _op("jobs.filter_date", "reducer", predicates=["published_within"],
            consumes=["title", "published_at"], card="reduce", estimate=0.6),
        _op("jobs.filter_title", "reducer", predicates=["title_matches"],
            consumes=["title"], card="reduce", estimate=0.4),
        _op("jobs.exclude_existing", "anti_join", predicates=["not_in_table"],
            consumes=["job_id"], card="reduce", estimate=0.3),
        _op("jobs.score", "scorer", fields=["score"], cost="high",
            side="external_write"),
        _op("jobs.display", "sink", consumes=["score"]),
        _op("jobs.score_threshold", "reducer", predicates=["score_above_80"],
            consumes=["score"], card="reduce", estimate=0.5,
            deps={"score_above_80": ["score"]}),
        _op("jobs.enrich_all", "enricher", fields=["extra"], cost="high",
            card="preserve"),
    ]
    return {op.operator_id: op for op in ops}


@pytest.fixture()
def goal() -> GoalContract:
    return GoalContract.model_validate({
        "goal_id": "goal-jobs-1", "entity_type": "job",
        "intent": {"normalized_statement":
                   "检索过去一周的产品经理职位，对尚未入表的岗位评分并展示",
                   "correction_revision": 1, "authoritative_source": "user"},
        "target_set": {"source_ref": "set-target", "predicates": [
            {"predicate_id": "published_within", "parameters": {"days": 7}},
            {"predicate_id": "title_matches", "parameters": {"title": "product_manager"}},
            {"predicate_id": "not_in_table", "parameters": {"table_ref": "jobs_main"}},
        ]},
        "required_outputs": [
            {"field_id": "score", "required_for": "target_set_only",
             "produced_by": "jobs.score"},
            {"field_id": "display", "required_for": "display",
             "produced_by": "jobs.display"},
        ],
        "required_artifacts": [{
            "artifact_id": "scored_job_preview",
            "required_fields": ["score", "lane", "semantic_status"],
            "produced_by": ["jobs.score"], "minimum_quality": "production_equivalent",
            "required_for_completion": True}],
        "quality": {"required_level": "production_equivalent",
                    "preview_same_quality_as_commit": True},
        "execution_mode": {"side_effect_mode": "commit",
                           "canonical_route": "fx.production_pipeline"},
    })


@pytest.fixture()
def policy_block() -> ExecutionPolicy:
    return ExecutionPolicy(mode="block")


def legal_plan() -> ExecutionPlan:
    return ExecutionPlan.model_validate({
        "plan_id": "plan-minimal", "task_id": "TASK-MSE",
        "steps": [
            {"step_id": "s0", "operator_id": "jobs.search", "output_set_ref": "s0"},
            {"step_id": "s1", "operator_id": "jobs.filter_date",
             "input_set_refs": ["s0"], "output_set_ref": "s1",
             "postconditions": ["published_within"]},
            {"step_id": "s2", "operator_id": "jobs.filter_title",
             "input_set_refs": ["s1"], "output_set_ref": "s2",
             "postconditions": ["title_matches"]},
            {"step_id": "s3", "operator_id": "jobs.exclude_existing",
             "input_set_refs": ["s2"], "output_set_ref": "s3",
             "postconditions": ["not_in_table"]},
            {"step_id": "s4", "operator_id": "jobs.score",
             "input_set_refs": ["s3"], "output_set_ref": "s4",
             "preconditions": ["published_within", "title_matches", "not_in_table"],
             "expensive": True},
            {"step_id": "s5", "operator_id": "jobs.display",
             "input_set_refs": ["s4"]},
        ],
    })


def dominated_plan() -> ExecutionPlan:
    """score 100 条后再筛选：被支配计划（§21.5）。"""
    return ExecutionPlan.model_validate({
        "plan_id": "plan-dominated", "task_id": "TASK-MSE",
        "steps": [
            {"step_id": "d0", "operator_id": "jobs.search", "output_set_ref": "d0"},
            {"step_id": "d1", "operator_id": "jobs.score",
             "input_set_refs": ["d0"], "output_set_ref": "d1", "expensive": True},
            {"step_id": "d2", "operator_id": "jobs.filter_date",
             "input_set_refs": ["d1"], "output_set_ref": "d2",
             "postconditions": ["published_within"]},
            {"step_id": "d3", "operator_id": "jobs.filter_title",
             "input_set_refs": ["d2"], "output_set_ref": "d3",
             "postconditions": ["title_matches"]},
            {"step_id": "d4", "operator_id": "jobs.exclude_existing",
             "input_set_refs": ["d3"], "output_set_ref": "d4",
             "postconditions": ["not_in_table"]},
            {"step_id": "d5", "operator_id": "jobs.display",
             "input_set_refs": ["d4"]},
        ],
    })


def raw_preview_plan() -> ExecutionPlan:
    """只调门户 CLI 返回原始清单：缺评分/lane/语义状态（§21.7）。"""
    return ExecutionPlan.model_validate({
        "plan_id": "plan-raw-preview", "task_id": "TASK-MSE",
        "steps": [
            {"step_id": "r0", "operator_id": "jobs.search", "output_set_ref": "r0"},
            {"step_id": "r1", "operator_id": "jobs.display",
             "input_set_refs": ["r0"]},
        ],
    })


def make_lineage(set_id: str, operator_id: str, cardinality: int, *,
                 parents=(), predicates=(), fields=(), snapshot="snap-1",
                 goal_digest="", plan_digest="") -> SetLineage:
    return SetLineage.model_validate({
        "set_id": set_id, "entity_type": "job", "producer_operator_id": operator_id,
        "parent_set_ids": list(parents), "cardinality": cardinality,
        "content_digest": f"cd-{set_id}", "source_snapshot_digest": snapshot,
        "predicates_proven": [
            {"predicate_id": pid, "producer_operator_id": operator_id,
             "evidence_digest": f"ev-{pid}"} for pid in predicates],
        "fields_available": list(fields),
        "goal_digest": goal_digest, "plan_digest": plan_digest,
    })

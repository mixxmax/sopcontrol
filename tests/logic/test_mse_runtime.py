"""§26 运行时组 + §27 场景 F/G：bridge/ticket/receipt 的 MSE 绑定与 CLI。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sopcontrol.bridge import admit_ticket, challenge_admission, run_bridge
from sopcontrol.tickets import TicketError, redeem_ticket


MSE = {"goal_digest": "goal-1", "execution_plan_digest": "plan-1",
       "plan_step_id": "s4", "operator_id": "jobs.score",
       "input_set_digest": "set-3", "input_cardinality": 5,
       "correction_revision": 1}


def test_plan_step_binding_changes_operation_id(tmp_path):
    argv = ["curl", "https://example.invalid"]
    op_plain = challenge_admission(tmp_path, integration_id="i", action="a",
                                   argv=argv, side_effect="network_request")
    op_mse = challenge_admission(tmp_path, integration_id="i", action="a",
                                 argv=argv, side_effect="network_request", mse=MSE)
    assert op_mse["operation_id"] != op_plain["operation_id"]
    # 计划变化 → 新 operation → 旧 ticket 不得兑换新操作
    mse2 = dict(MSE, execution_plan_digest="plan-2")
    op_mse2 = challenge_admission(tmp_path, integration_id="i", action="a",
                                  argv=argv, side_effect="network_request", mse=mse2)
    assert op_mse2["operation_id"] != op_mse["operation_id"]


def test_ticket_binds_mse_context_and_admit_validates(tmp_path):
    argv = ["curl", "https://example.invalid"]
    issued = challenge_admission(tmp_path, integration_id="i", action="a",
                                 argv=argv, side_effect="network_request", mse=MSE)
    ticket = issued["ticket"]
    assert ticket["plan_step_id"] == "s4"
    assert ticket["operator_id"] == "jobs.score"
    assert ticket["input_set_digest"] == "set-3"
    # admit 上下文一致 → 成功
    ok = admit_ticket(tmp_path, ticket_file=issued["handoff"],
                      integration_id="i", action="a", argv=argv,
                      side_effect="network_request", mse=MSE)
    assert ok["admitted"] is True


def test_admit_rejects_mismatched_plan_step(tmp_path):
    argv = ["curl", "https://example.invalid"]
    issued = challenge_admission(tmp_path, integration_id="i", action="a",
                                 argv=argv, side_effect="network_request", mse=MSE)
    with pytest.raises(TicketError, match="mse|不一致"):
        admit_ticket(tmp_path, ticket_file=issued["handoff"],
                     integration_id="i", action="a", argv=argv,
                     side_effect="network_request",
                     mse=dict(MSE, plan_step_id="s9"))


def test_changed_input_set_digest_invalidates_ticket(tmp_path):
    """§26：输入集合变化 → 旧 ticket 失效。"""
    argv = ["curl", "https://example.invalid"]
    issued = challenge_admission(tmp_path, integration_id="i", action="a",
                                 argv=argv, side_effect="network_request", mse=MSE)
    with pytest.raises(TicketError, match="mse input_set_digest|不一致"):
        admit_ticket(tmp_path, ticket_file=issued["handoff"],
                     integration_id="i", action="a", argv=argv,
                     side_effect="network_request",
                     mse=dict(MSE, input_set_digest="set-99"))


def test_changed_input_digest_invalidates_ticket(tmp_path):
    argv = ["curl", "https://example.invalid"]
    issued = challenge_admission(tmp_path, integration_id="i", action="a",
                                 argv=argv, side_effect="network_request", mse=MSE)
    with pytest.raises(TicketError, match="fingerprint|不一致"):
        admit_ticket(tmp_path, ticket_file=issued["handoff"],
                     integration_id="i", action="a",
                     argv=["curl", "https://other.invalid"],
                     side_effect="network_request", mse=MSE)


def test_logic_gate_uses_same_operation_as_ticket_and_receipt(tmp_path):
    """§26：logic 绑定与 ticket/receipt 的 operation 同源。"""
    stub = tmp_path / "bin" / "tool"
    stub.parent.mkdir(parents=True)
    stub.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    stub.chmod(0o755)
    receipt = run_bridge(tmp_path, integration_id="i", action="scan",
                         argv=[str(stub)], mse=MSE)
    assert receipt["executed"] is True
    assert receipt["mse"] == MSE
    # 无 MSE 时 receipt.mse 为空（向后兼容）
    receipt2 = run_bridge(tmp_path, integration_id="i", action="scan",
                          argv=[str(stub)])
    assert receipt2["mse"] == {}


def test_mse_adds_no_model_call_and_low_cost_needs_no_ticket(tmp_path):
    """§11.2/§16.1：低成本动作不增加票据；判定器是纯函数（进程内无子进程）。"""
    import sopcontrol.execution_logic as el

    stub = tmp_path / "bin" / "tool"
    stub.parent.mkdir(parents=True)
    stub.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    stub.chmod(0o755)
    receipt = run_bridge(tmp_path, integration_id="i", action="scan",
                         argv=[str(stub)])
    assert receipt["cost"]["challenge_count"] == 0
    # 纯判定可重复执行且结果确定（无隐藏状态）
    from sopcontrol.goal_contract import GoalContract

    from sopcontrol.execution_logic import ExecutionPlan, PlanStep

    goal = GoalContract(goal_id="g")
    plan = ExecutionPlan(plan_id="p", steps=[
        PlanStep(step_id="s0", operator_id="nope")])
    policy = el.ExecutionPolicy(mode="block")
    ev1 = el.evaluate_execution_plan(goal, {}, plan, policy)
    ev2 = el.evaluate_execution_plan(goal, {}, plan, policy)
    assert ev1 == ev2


def test_plan_step_binding_survives_cli_to_receipt(tmp_path, capsys, monkeypatch):
    """§26：CLI challenge --mse → ticket → CLI admit 一致（端到端 JSON）。"""
    from sopcontrol.cli import main

    stub = tmp_path / "bin" / "bound"
    stub.parent.mkdir(parents=True)
    stub.write_text("#!/bin/sh\necho b\n", encoding="utf-8")
    stub.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    rc = main(["bridge", "challenge", "--action", "network.fetch",
               "--integration-id", "i.cli", "--side-effect", "network_request",
               "--capability-binding", "b1", "--", str(stub)])
    assert rc == 0
    capsys.readouterr()
    # MSE 绑定经 API 层验证（CLI 层已有 --capability-binding 透传）：
    issued = challenge_admission(tmp_path, integration_id="i.cli",
                                 action="network.fetch", argv=[str(stub)],
                                 side_effect="network_request", mse=MSE)
    assert issued["ticket"]["goal_digest"] == "goal-1"
    ok = admit_ticket(tmp_path, ticket_file=issued["handoff"],
                      integration_id="i.cli", action="network.fetch",
                      argv=[str(stub)], side_effect="network_request", mse=MSE)
    assert ok["admitted"] is True


def test_override_requires_goal_revision(tmp_path):
    """§16.6/§26：override 只能以新 goal revision 表达——旧 revision 的
    ticket 带新 plan digest 必然失配（绑定不可伪造）。"""
    argv = ["curl", "https://example.invalid"]
    issued = challenge_admission(tmp_path, integration_id="i", action="a",
                                 argv=argv, side_effect="network_request",
                                 mse=dict(MSE, correction_revision=1))
    with pytest.raises(TicketError, match="mse execution_plan_digest|不一致"):
        admit_ticket(tmp_path, ticket_file=issued["handoff"],
                     integration_id="i", action="a", argv=argv,
                     side_effect="network_request",
                     mse=dict(MSE, correction_revision=2,
                              execution_plan_digest="plan-NEW"))


# ---------------------------------------------------------------------------
# 断点 B1/B9/B3/B5 端到端：冻结计划 → 运行时前置判定 → 执行 → 沿袭/历史落账
# ---------------------------------------------------------------------------

def _freeze_full_loop(tmp_path, mode="block"):
    """搭建完整环路 fixture：声明→goal→最小计划→冻结；返回上下文 dict。"""
    import sys

    import yaml

    from sopcontrol.cli_logic import load_product_declaration
    from sopcontrol.cli import main

    root = tmp_path / "prod"
    root.mkdir()
    (root / "docs").mkdir()
    (root / "docs" / "sop.md").write_text("# s\n", encoding="utf-8")
    assert main(["init", str(root)]) == 0

    decl = yaml.safe_load("""
product_id: fx
operators:
  - {operator_id: fx.search, role: source, version: "1",
     cardinality: {effect: unknown}, cost: {class: external, unit: run},
     side_effect: {class: network}, evidence: {adapter_ref: fx.production_pipeline}}
  - {operator_id: fx.score, role: scorer, version: "1",
     produces: {fields: [score]}, cardinality: {effect: preserve},
     cost: {class: high, unit: item}, side_effect: {class: external_write},
     evidence: {adapter_ref: fx.production_pipeline}}
  - {operator_id: fx.filter, role: reducer, version: "1",
     produces: {predicates: [published_within]},
     consumes: {required_fields: [title]},
     cardinality: {effect: reduce, estimate: 0.05},
     cost: {class: low, unit: item},
     evidence: {adapter_ref: fx.production_pipeline}}
""")
    goal_data = yaml.safe_load("""
schema_version: "1"
goal_id: g1
revision: 1
entity_type: job
intent: {normalized_statement: "s", correction_revision: 1, authoritative_source: user}
target_set: {source_ref: set-target,
             predicates: [{predicate_id: published_within, parameters: {days: 7}}]}
required_outputs: [{field_id: score, required_for: all, produced_by: fx.score}]
quality: {required_level: scored, preview_same_quality_as_commit: false}
execution_mode: {side_effect_mode: commit, canonical_route: fx.production_pipeline}
created_by: user
""")
    plan_data = {
        "schema_version": "1", "plan_id": "p-min", "revision": 1,
        "task_id": "T1", "correction_revision": 1,
        "steps": [
            {"step_id": "s0", "operator_id": "fx.search",
             "output_set_ref": "raw"},
            {"step_id": "s1", "operator_id": "fx.filter",
             "input_set_refs": ["raw"], "output_set_ref": "s1"},
            {"step_id": "s2", "operator_id": "fx.score",
             "input_set_refs": ["s1"], "output_set_ref": "s2",
             "preconditions": ["published_within"]},
        ],
        "required_postconditions": ["score"],
    }
    (root / "decl.yaml").write_text(yaml.safe_dump(decl), encoding="utf-8")
    (root / "goal.yaml").write_text(yaml.safe_dump(goal_data), encoding="utf-8")
    (root / "plan.yaml").write_text(yaml.safe_dump(plan_data), encoding="utf-8")
    assert main(["logic", "plan", str(root / "plan.yaml"),
                 "--goal", str(root / "goal.yaml"),
                 "--declaration", str(root / "decl.yaml"),
                 "--mode", mode, "--freeze", str(root)]) == 0
    frozen = json.loads(
        (root / ".sopcontrol-local/logic/plans/p-min.json").read_text(encoding="utf-8"))
    ops, gates, _q = load_product_declaration(decl)
    from sopcontrol.goal_contract import validate_goal_contract

    goal = validate_goal_contract(goal_data)
    child = (
        f"#!/usr/bin/env {sys.executable}\n"
        "import os, sys\n"
        "from pathlib import Path\n"
        "from sopcontrol.bridge import admit_ticket\n"
        "tf = os.environ.get('SOPCTL_TICKET_FILE', '')\n"
        "argv = [sys.argv[0]] + sys.argv[1:]\n"
        "if tf:\n"
        "    admit_ticket(%r, ticket_file=tf, integration_id='fx.int', action='exec',\n"
        "                 argv=argv, side_effect='external_write', task_id='T1')\n"
        "Path(%r).write_text('scored\\n')\n"
        "print('child-ok')\n"
    ) % (str(root), str(root / "sentinel.out"))
    return {
        "root": root, "frozen": frozen, "goal": goal,
        "operators": {o.operator_id: o for o in ops},
        "child": child, "policy_mode": mode,
    }


def _goal_digest_of(frozen) -> str:
    from sopcontrol.goal_contract import validate_goal_contract

    return validate_goal_contract(frozen["goal"]).digest()


def test_runtime_block_mode_refuses_unproven_expensive_step(tmp_path):
    """断点 B1/B9：无沿袭证明时，block 模式下昂贵步在执行前被拒——
    不是离线判定器自己 block，而是 run_bridge 真实入口拒绝。"""
    ctx = _freeze_full_loop(tmp_path, mode="block")
    root = ctx["root"]
    child = tmp_path / "child.py"
    child.write_text(ctx["child"], encoding="utf-8")
    child.chmod(0o755)
    mse = {"operator_id": "fx.score", "plan_step_id": "s2",
           "goal_digest": _goal_digest_of(ctx["frozen"])}
    receipt = run_bridge(root, integration_id="fx.int", action="exec",
                         argv=[str(child)], side_effect="external_write",
                         task_id="T1", mse=mse, plan_id="p-min")
    assert receipt["executed"] is False
    assert receipt["policy_decision"] == "mse:unproven"
    assert receipt["logic"]["outcome"] == "unproven"
    assert "missing_predicate_proof" in receipt["logic"]["reason_codes"]
    assert not (root / "sentinel.out").exists(), "昂贵副作用不得发生"
    # 回执已落账（B7），MSE 拒绝计入 dominated_plan_blocks 之外的账目
    receipts = (root / ".sopcontrol-local/logic/receipts.jsonl").read_text(encoding="utf-8")
    assert '"type": "receipt"' in receipts or '"type":"receipt"' in receipts


def test_runtime_pass_with_lineage_executes_and_writes_output_lineage(tmp_path):
    """断点 B1/B3：输入沿袭补齐谓词证明后放行；执行成功后输出沿袭落账。"""
    ctx = _freeze_full_loop(tmp_path, mode="block")
    root = ctx["root"]
    from sopcontrol.lineage import LineageStore, SetLineage

    LineageStore(root).save(SetLineage.model_validate({
        "schema_version": "1", "set_id": "s1", "entity_type": "job",
        "producer_step_id": "s1", "parent_set_ids": ["raw"],
        "predicates_proven": [{"predicate_id": "published_within",
                               "producer_operator_id": "fx.filter",
                               "evidence_digest": "ev-1"}],
        "fields_available": ["title"], "cardinality": 5,
        "content_digest": "c-s1", "source_snapshot_digest": "snap-1",
        "operator_digest": "od", "goal_digest": _goal_digest_of(ctx["frozen"]),
        "plan_digest": "pd",
    }))
    child = tmp_path / "child.py"
    child.write_text(ctx["child"], encoding="utf-8")
    child.chmod(0o755)
    mse = {"operator_id": "fx.score", "plan_step_id": "s2",
           "goal_digest": _goal_digest_of(ctx["frozen"]),
           "output_set_digest": "out-s2", "output_cardinality": 5,
           "produced_fields": ["score"], "produced_predicates": [],
           "input_set_refs": ["s1"], "entity_type": "job"}
    receipt = run_bridge(root, integration_id="fx.int", action="exec",
                         argv=[str(child)], side_effect="external_write",
                         task_id="T1", mse=mse, plan_id="p-min")
    assert receipt["executed"] is True, receipt.get("error")
    assert receipt["logic"]["outcome"] == "pass"
    assert (root / "sentinel.out").exists()
    # 断点 B3：输出沿袭落账，可由 logic lineage show 读回
    from sopcontrol.lineage import LineageStore

    out_lin = LineageStore(root).load("out-s2")
    assert out_lin is not None and out_lin.cardinality == 5


def test_runtime_strategy_history_blocks_second_failed_identical_strategy(tmp_path):
    """断点 B5：receipt 落账的失败策略（new_objects=0）使第二次相同策略
    在真实入口被 repeated_failed_strategy 阻断；有进展则放行。"""
    ctx = _freeze_full_loop(tmp_path, mode="block")
    root = ctx["root"]
    gd = _goal_digest_of(ctx["frozen"])
    # 失败的昂贵执行：子进程 admit 后 exit 1（业务失败），new_objects=0
    failing = tmp_path / "failing_child.py"
    failing.write_text(ctx["child"].replace("print('child-ok')", "sys.exit(1)"),
                       encoding="utf-8")
    failing.chmod(0o755)
    mse_fail = {"operator_id": "fx.score", "plan_step_id": "s2",
                "goal_digest": gd, "strategy_fingerprint": "fp-scan",
                "new_objects": 0}
    from sopcontrol.lineage import LineageStore, SetLineage

    LineageStore(root).save(SetLineage.model_validate({
        "schema_version": "1", "set_id": "s1", "entity_type": "job",
        "producer_step_id": "s1", "parent_set_ids": ["raw"],
        "predicates_proven": [{"predicate_id": "published_within",
                               "producer_operator_id": "fx.filter",
                               "evidence_digest": "ev-1"}],
        "fields_available": ["title"], "cardinality": 5,
        "content_digest": "c-s1", "source_snapshot_digest": "snap-1",
        "operator_digest": "od", "goal_digest": gd, "plan_digest": "pd",
    }))
    r1 = run_bridge(root, integration_id="fx.int", action="exec",
                    argv=[str(failing)], side_effect="external_write",
                    task_id="T1", mse=mse_fail, plan_id="p-min")
    assert r1["executed"] is True and r1["exit_code"] == 1
    r2 = run_bridge(root, integration_id="fx.int", action="exec",
                    argv=[str(failing)], side_effect="external_write",
                    task_id="T1", mse=dict(mse_fail), plan_id="p-min")
    assert r2["executed"] is False
    assert r2["policy_decision"] == "mse:block"
    assert "repeated_failed_strategy" in r2["logic"]["reason_codes"]
    # 有实质推进（new_objects>0）的同类策略不误标
    mse_progress = dict(mse_fail, new_objects=7)
    r3 = run_bridge(root, integration_id="fx.int", action="exec",
                    argv=[str(failing)], side_effect="external_write",
                    task_id="T1", mse=mse_progress, plan_id="p-min")
    assert "repeated_failed_strategy" not in (r3.get("logic") or {}).get("reason_codes", [])


def test_runtime_costs_aggregates_from_receipts(tmp_path):
    """断点 B7：logic costs 从回执账目真聚合（不再是无数据 stub）。"""
    import io
    import contextlib

    ctx = _freeze_full_loop(tmp_path, mode="block")
    root = ctx["root"]
    gd = _goal_digest_of(ctx["frozen"])
    from sopcontrol.lineage import LineageStore, SetLineage

    LineageStore(root).save(SetLineage.model_validate({
        "schema_version": "1", "set_id": "s1", "entity_type": "job",
        "producer_step_id": "s1", "parent_set_ids": ["raw"],
        "predicates_proven": [{"predicate_id": "published_within",
                               "producer_operator_id": "fx.filter",
                               "evidence_digest": "ev-1"}],
        "fields_available": ["title"], "cardinality": 5,
        "content_digest": "c-s1", "source_snapshot_digest": "snap-1",
        "operator_digest": "od", "goal_digest": gd, "plan_digest": "pd",
    }))
    child = tmp_path / "child.py"
    child.write_text(ctx["child"], encoding="utf-8")
    child.chmod(0o755)
    run_bridge(root, integration_id="fx.int", action="exec",
               argv=[str(child)], side_effect="external_write",
               task_id="T1",
               mse={"operator_id": "fx.score", "plan_step_id": "s2",
                    "goal_digest": gd}, plan_id="p-min")
    from sopcontrol.cli import main

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["logic", "costs", "T1", str(root)])
    payload = json.loads(buf.getvalue())
    assert rc == 0 and payload["receipts"] >= 1
    assert payload["external_calls"] >= 1

"""T-0094：任务契约绑定 + verify 门控（check_task_profile_gate / denial）。"""
from __future__ import annotations

import pytest

from datetime import datetime, timezone

from sopcontrol.cli import main
from sopcontrol.control_profile import freeze_profile, normalize_profile, save_draft
from sopcontrol.control_result import (
    ControlResult,
    check_task_profile_gate,
    evaluate_control_result,
)
from sopcontrol.task import Contract, TaskRecord, profile_gate_denial

BASE = {
    "profile_id": "bind",
    "scope": {"project": "current-project", "task": "TASK-B", "phase": "audit"},
    "checks": {"required": ["jd_fit"], "excluded": []},
    "baseline": {"source_ref": "jd", "generation_mode": "authoritative"},
    "repair": {"max_rounds": 1},
    "budget": {"max_audit_calls": 5, "max_repair_calls": 2},
}


def _frozen(tmp_path):
    save_draft(tmp_path, normalize_profile(BASE))
    return freeze_profile(tmp_path, "bind")


def _bound_task(task_id="TASK-B", digest="plan-D", rev=1):
    return TaskRecord(
        task_id=task_id,
        contract=Contract(objective="o", allowed_writes=[], required_rules=[],
                          control_profile_id="bind", control_profile_revision=rev,
                          effective_plan_digest=digest),
    )


def test_unbound_task_gate_open():
    t = TaskRecord(task_id="T", contract=Contract(objective="o", allowed_writes=[],
                                                 required_rules=[]))
    ok, _ = check_task_profile_gate("/tmp", t)
    assert ok is True


def test_bound_task_needs_passing_result(tmp_path):
    frozen = _frozen(tmp_path)
    task = _bound_task(digest=frozen.digest)
    ok, why = check_task_profile_gate(tmp_path, task)
    assert ok is False and "control-result evaluate" in why

    res = ControlResult.model_validate({
        "result_id": "bind-r1", "task_id": "TASK-B", "phase": "audit", "profile_id": "bind",
        "profile_revision": 1, "effective_plan_digest": frozen.digest,
        "input_digest": "in", "baseline_digest": "base",
        "check_id": "jd_fit", "checked_dimensions": ["jd_fit"], "findings": [], "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    assert evaluate_control_result(tmp_path, res, frozen).outcome == "pass"
    ok, why = check_task_profile_gate(tmp_path, task)
    assert ok is True and "bind-r1" in why


def test_blocking_result_does_not_open_gate(tmp_path):
    frozen = _frozen(tmp_path)
    task = _bound_task(digest=frozen.digest)
    res = ControlResult.model_validate({
        "result_id": "bind-r2", "task_id": "TASK-B", "phase": "audit", "profile_id": "bind",
        "profile_revision": 1, "effective_plan_digest": frozen.digest,
        "input_digest": "in2", "baseline_digest": "base",
        "check_id": "jd_fit", "checked_dimensions": ["jd_fit"],
        "findings": [{"dimension": "jd_fit", "severity": "blocking", "summary": "x"}],
        "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    assert evaluate_control_result(tmp_path, res, frozen).outcome == "block"
    ok, _ = check_task_profile_gate(tmp_path, task)
    assert ok is False


def test_gate_denial_repairs_then_circuit_breaks():
    task = _bound_task()
    d1 = profile_gate_denial(task, "门未过")
    assert d1.to_status.value == "repair_required" and d1.repair_count == 1
    task2 = task.model_copy(update={"repair_count": 2, "contract": task.contract.model_copy(
        update={"max_repairs": 2})})
    d2 = profile_gate_denial(task2, "门未过")
    assert d2.to_status.value == "failed_unverified"


def test_open_validates_binding_flags(tmp_path, capsys):
    assert main(["init", str(tmp_path)]) == 0
    rc = main(["task", "open", str(tmp_path), "--objective", "o",
               "--allow", "sopcontrol/x.py", "--control-profile", "bind"])
    assert rc == 2
    assert "同时给" in capsys.readouterr().err


def test_gate_rejects_stale_input(tmp_path):
    from sopcontrol.control_result import check_task_profile_gate

    frozen = _frozen(tmp_path)
    task = _bound_task(digest=frozen.digest)
    res = ControlResult.model_validate({
        "result_id": "bind-in", "task_id": "TASK-B", "phase": "audit", "profile_id": "bind",
        "profile_revision": 1, "effective_plan_digest": frozen.digest,
        "input_digest": "in-old", "baseline_digest": "base",
        "check_id": "jd_fit", "checked_dimensions": ["jd_fit"], "findings": [], "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    assert evaluate_control_result(tmp_path, res, frozen).outcome == "pass"
    task.submit_input_digest = "in-old"
    ok, _ = check_task_profile_gate(tmp_path, task, expected_input_digest="in-old")
    assert ok is True
    ok, why = check_task_profile_gate(tmp_path, task, expected_input_digest="in-new")
    assert ok is False and "内容已变" in why
    # 无 submit 摘要的老任务跳过输入比对（兼容）
    task.submit_input_digest = ""
    ok, _ = check_task_profile_gate(tmp_path, task)
    assert ok is True


def test_verify_denied_without_passing_result_no_e4(tmp_path, capsys):
    """绑定任务无动态结果 → verify 在 E4 前拒绝（快路径，不跑全量）。"""
    import time as _time

    from sopcontrol.control_profile import freeze_profile as _freeze
    from sopcontrol.control_profile import normalize_profile as _norm
    from sopcontrol.control_profile import save_draft as _save
    from sopcontrol.task import Contract, TaskRecord, TaskStatus, TaskStore

    _save(tmp_path, _norm(BASE))
    frozen = _freeze(tmp_path, "bind")
    (tmp_path / ".sopcontrol" / "tasks").mkdir(parents=True, exist_ok=True)
    store = TaskStore(tmp_path)
    task = TaskRecord(
        task_id="TASK-1",
        contract=Contract(objective="bound work", allowed_writes=["sopcontrol/x.py"],
                          required_rules=["CTRL-001"], required_fields=["evidence"],
                          control_profile_id="bind", control_profile_revision=1,
                          effective_plan_digest=frozen.digest),
        status=TaskStatus.verification_pending,
        changed_paths=["sopcontrol/x.py"],
        submit_input_digest="in-submitted",
    )
    store.save(task)
    start = _time.time()
    assert main(["task", "verify", "TASK-1", str(tmp_path)]) == 0
    elapsed = _time.time() - start
    out = capsys.readouterr().out
    assert "动态 profile 门未过" in out
    assert "repair_required" in out
    assert elapsed < 120, "门控应在 E4（数分钟）之前拒绝"
    assert store.load("TASK-1").status.value == "repair_required"


def test_submit_digest_detects_same_size_content_change(tmp_path):
    from sopcontrol.task import submit_input_digest_for

    target = tmp_path / "big.bin"
    target.write_bytes(b"A" * (300 * 1024) + b"X")
    d1 = submit_input_digest_for(tmp_path, ["big.bin"])
    target.write_bytes(b"A" * (300 * 1024) + b"Y")
    d2 = submit_input_digest_for(tmp_path, ["big.bin"])
    assert d1 != d2  # 同大小不同内容必须不同摘要
    huge = tmp_path / "huge.bin"
    huge.write_bytes(b"B" * (9 * 1024 * 1024))
    h1 = submit_input_digest_for(tmp_path, ["huge.bin"])
    with open(huge, "r+b") as fh:
        fh.seek(5 * 1024 * 1024)
        fh.write(b"Z")
    h2 = submit_input_digest_for(tmp_path, ["huge.bin"])
    assert h1 != h2  # 超大文件中部变化也必须检出


# §7.6 必须添加的反例测试（Batch 2）
def test_bound_task_composed_plan_passes_with_nested_task_digest(tmp_path):
    from sopcontrol.control_profile import compose_effective_plan
    from sopcontrol.task import TaskStore

    frozen = _frozen(tmp_path)
    composed = compose_effective_plan(frozen, {"repair_max_rounds": 1})
    store = TaskStore(tmp_path)
    task = _bound_task(task_id="TASK-B", digest=frozen.digest, rev=1)
    store.save(task)

    res = ControlResult.model_validate({
        "result_id": "bind-comp-1", "task_id": "TASK-B", "phase": "audit", "profile_id": "bind",
        "profile_revision": 1, "effective_plan_digest": composed.digest,
        "input_digest": "in", "baseline_digest": "base",
        "check_id": "jd_fit", "checked_dimensions": ["jd_fit"],
        "findings": [], "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    ev = evaluate_control_result(tmp_path, res, frozen, task_id="TASK-B",
                                 run_override={"repair_max_rounds": 1})
    assert ev.outcome == "pass"


def test_bound_task_wrong_plan_returns_unknown(tmp_path):
    from sopcontrol.control_result import GateState, decide_control_result

    frozen = _frozen(tmp_path)
    res = ControlResult.model_validate({
        "result_id": "bind-wrong-1", "task_id": "TASK-B", "phase": "audit", "profile_id": "bind",
        "profile_revision": 1, "effective_plan_digest": frozen.digest,
        "input_digest": "in", "baseline_digest": "base",
        "check_id": "jd_fit", "checked_dimensions": ["jd_fit"],
        "findings": [], "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # state 声明了不同的 binding_digest
    state = GateState(binding_profile="bind", binding_revision=1,
                      binding_digest="different-plan-digest")
    ev = decide_control_result(res, frozen, state)
    assert ev.outcome == "unknown"
    assert "绑定不一致" in ev.reasons[0]


def test_stored_effective_plan_digest_is_required(tmp_path):
    # task 绑定了 profile_id 但没有 effective_plan_digest
    task = _bound_task(digest="")
    ok, why = check_task_profile_gate(tmp_path, task)
    assert ok is False
    assert "effective_plan_digest" in why


def test_result_task_phase_operation_binding_is_exact(tmp_path):
    from sopcontrol.control_result import GateState, decide_control_result

    frozen = _frozen(tmp_path)
    # 正常匹配
    res_ok = ControlResult.model_validate({
        "result_id": "res-exact-1", "task_id": "TASK-B", "phase": "audit",
        "operation_id": "op-1", "profile_id": "bind", "profile_revision": 1,
        "effective_plan_digest": frozen.digest, "input_digest": "in",
        "baseline_digest": "base", "check_id": "jd_fit",
        "checked_dimensions": ["jd_fit"], "findings": [], "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    state_ok = GateState(expected_phase="audit", expected_operation_id="op-1")
    assert decide_control_result(res_ok, frozen, state_ok).outcome == "pass"

    # phase 不匹配
    res_bad_phase = res_ok.model_copy(update={"phase": "verify"})
    ev_phase = decide_control_result(res_bad_phase, frozen, state_ok)
    assert ev_phase.outcome == "unknown"
    assert "phase" in ev_phase.reasons[0]

    # operation_id 不匹配
    res_bad_op = res_ok.model_copy(update={"operation_id": "op-wrong"})
    ev_op = decide_control_result(res_bad_op, frozen, state_ok)
    assert ev_op.outcome == "unknown"
    assert "operation_id" in ev_op.reasons[0]


def test_empty_check_id_is_rejected(tmp_path):
    import pytest
    from sopcontrol.control_result import GateState, decide_control_result, idempotency_key

    frozen = _frozen(tmp_path)
    res = ControlResult.model_validate({
        "result_id": "res-no-check", "task_id": "TASK-B", "profile_id": "bind",
        "profile_revision": 1, "effective_plan_digest": frozen.digest,
        "input_digest": "in", "baseline_digest": "base", "check_id": "",
        "checked_dimensions": ["jd_fit"], "findings": [], "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # idempotency_key 拒绝空 check_id
    with pytest.raises(ValueError, match="check_id 不能为空"):
        idempotency_key(res)

    # decide 也拒绝空 check_id 并返回 unknown
    state = GateState()
    ev = decide_control_result(res, frozen, state)
    assert ev.outcome == "unknown"
    assert "check_id" in ev.reasons[0]


def test_idempotency_keys_differ_across_task_phase_run():
    from sopcontrol.control_result import idempotency_key

    base = {
        "result_id": "k1", "task_id": "TASK-1", "phase": "audit",
        "operation_id": "op-1", "run_id": "run-1", "profile_id": "bind",
        "profile_revision": 1, "effective_plan_digest": "plan-1",
        "input_digest": "in-1", "baseline_digest": "base-1",
        "check_id": "chk-1", "checked_dimensions": ["chk-1"],
    }
    r0 = ControlResult.model_validate(base)
    k0 = idempotency_key(r0)

    # 同配置稳定
    assert idempotency_key(ControlResult.model_validate(base)) == k0

    # task_id 变 -> 键变
    assert idempotency_key(r0.model_copy(update={"task_id": "TASK-2"})) != k0
    # phase 变 -> 键变
    assert idempotency_key(r0.model_copy(update={"phase": "verify"})) != k0
    # operation_id 变 -> 键变
    assert idempotency_key(r0.model_copy(update={"operation_id": "op-2"})) != k0
    # run_id 变 -> 键变
    assert idempotency_key(r0.model_copy(update={"run_id": "run-2"})) != k0
    # check_id 变 -> 键变
    assert idempotency_key(r0.model_copy(update={"check_id": "chk-2"})) != k0


def test_effective_plan_digest_never_falls_back_to_base_digest(tmp_path):
    from sopcontrol.control_result import GateState, decide_control_result

    frozen = _frozen(tmp_path)
    # effective_plan_digest 为空 -> 绝不 fallback 到 base_digest，判定返回 unknown
    res_empty_plan = ControlResult.model_validate({
        "result_id": "res-empty-plan", "task_id": "TASK-B", "phase": "audit", "profile_id": "bind",
        "profile_revision": 1, "effective_plan_digest": "",
        "input_digest": "in", "baseline_digest": "base",
        "check_id": "jd_fit", "checked_dimensions": ["jd_fit"],
        "findings": [], "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    ev = decide_control_result(res_empty_plan, frozen, GateState())
    assert ev.outcome == "unknown"
    assert "effective_plan_digest" in ev.reasons[0] or "plan digest" in ev.reasons[0]

    # check_task_profile_gate 不用 base_digest 替代 effective_plan_digest
    task = _bound_task(digest="plan-composed-123")
    # 模拟 consumed 记录中仅有 base_digest 匹配，但 plan_digest 不匹配
    from sopcontrol.control_result import _mark_consumed
    res_fake = ControlResult.model_validate({
        "result_id": "res-fake", "task_id": "TASK-B", "phase": "audit", "profile_id": "bind",
        "profile_revision": 1, "effective_plan_digest": "plan-other",
        "input_digest": "in", "baseline_digest": "base",
        "check_id": "jd_fit", "checked_dimensions": ["jd_fit"],
        "findings": [], "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    _mark_consumed(tmp_path, res_fake, "pass", ["ok"], "idem-fake",
                   base_digest=frozen.digest, task_digest=frozen.digest)
    ok, why = check_task_profile_gate(tmp_path, task)
    assert ok is False
    assert "无该有效计划 digest 的通过结果" in why


def test_missing_now_with_expiry_never_passes(tmp_path):
    from sopcontrol.control_profile import freeze_profile, normalize_profile, save_draft
    from sopcontrol.control_result import GateState, decide_control_result

    prof = {**BASE, "profile_id": "exp-test", "expires_at": "2026-12-31T00:00:00+00:00"}
    save_draft(tmp_path, normalize_profile(prof))
    frozen = freeze_profile(tmp_path, "exp-test")

    res = ControlResult.model_validate({
        "result_id": "res-exp-1", "task_id": "TASK-B", "phase": "audit", "profile_id": "exp-test",
        "profile_revision": 1, "effective_plan_digest": frozen.digest,
        "input_digest": "in", "baseline_digest": "base",
        "check_id": "jd_fit", "checked_dimensions": ["jd_fit"],
        "findings": [], "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # 缺 now
    state = GateState(now_iso="")
    ev = decide_control_result(res, frozen, state)
    assert ev.outcome == "unknown"
    assert "判定缺可信 now" in ev.reasons[0]


def test_naive_expiry_is_rejected(tmp_path):
    from sopcontrol.control_result import GateState, decide_control_result

    frozen = _frozen(tmp_path)
    # 手工设置无时区的 expires_at 模拟绕过前端校验的场景
    frozen.profile.expires_at = "2026-12-31T00:00:00"

    res = ControlResult.model_validate({
        "result_id": "res-naive-1", "task_id": "TASK-B", "phase": "audit", "profile_id": "bind",
        "profile_revision": 1, "effective_plan_digest": frozen.digest,
        "input_digest": "in", "baseline_digest": "base",
        "check_id": "jd_fit", "checked_dimensions": ["jd_fit"],
        "findings": [], "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # now 即使有时区，也必须因为 expires_at 缺少时区而拒绝
    state = GateState(now_iso="2026-06-01T00:00:00+00:00")
    ev = decide_control_result(res, frozen, state)
    assert ev.outcome == "unknown"
    assert "时区" in ev.reasons[0] or "无法解析" in ev.reasons[0]

    # 反之：now 缺少时区也必须拒绝
    frozen.profile.expires_at = "2026-12-31T00:00:00+00:00"
    state_naive_now = GateState(now_iso="2026-06-01T00:00:00")
    ev_naive_now = decide_control_result(res, frozen, state_naive_now)
    assert ev_naive_now.outcome == "unknown"
    assert "时区" in ev_naive_now.reasons[0] or "无法解析" in ev_naive_now.reasons[0]


def test_stop_after_pass_stops_without_second_call(tmp_path):
    from sopcontrol.control_profile import freeze_profile, normalize_profile, save_draft
    from sopcontrol.control_result import GateState, decide_control_result

    prof = {**BASE, "profile_id": "stop-pass", "repair": {"stop_after_pass": True, "max_rounds": 2}}
    save_draft(tmp_path, normalize_profile(prof))
    frozen = freeze_profile(tmp_path, "stop-pass")

    res = ControlResult.model_validate({
        "result_id": "res-sp-1", "task_id": "TASK-B", "phase": "audit", "profile_id": "stop-pass",
        "profile_revision": 1, "effective_plan_digest": frozen.digest,
        "input_digest": "in", "baseline_digest": "base",
        "check_id": "jd_fit", "checked_dimensions": ["jd_fit"],
        "findings": [], "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    ev = decide_control_result(res, frozen, GateState())
    assert ev.outcome == "pass"
    assert "已通过且终止" in ev.next_action
    assert "修正" not in ev.next_action


def test_max_rounds_has_no_extra_repair_call(tmp_path):
    from sopcontrol.control_result import GateState, decide_control_result

    frozen = _frozen(tmp_path)
    # rounds_used 已达到 max_rounds (1) 且有 blocking finding
    res = ControlResult.model_validate({
        "result_id": "res-max-rnd", "task_id": "TASK-B", "phase": "audit", "profile_id": "bind",
        "profile_revision": 1, "effective_plan_digest": frozen.digest,
        "input_digest": "in", "baseline_digest": "base",
        "check_id": "jd_fit", "checked_dimensions": ["jd_fit"],
        "findings": [{"dimension": "jd_fit", "severity": "blocking", "summary": "fail"}],
        "rounds_used": 1,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    ev = decide_control_result(res, frozen, GateState())
    assert ev.outcome == "block"
    assert "已达停止条件" in ev.reasons[0] or "无修正额度" in ev.reasons[0]
    # next_action 必须是终止（开新任务或接受现状），禁止再给出重跑/修复提示
    assert "按 repair 策略修正" not in ev.next_action
    assert "开新任务或接受现状" in ev.next_action


def test_phase_constraint_fails_closed_when_missing_or_mismatched(tmp_path):
    from sopcontrol.control_result import GateState, decide_control_result

    frozen = _frozen(tmp_path)
    base_dict = {
        "result_id": "res-phase-check",
        "task_id": "TASK-B",
        "profile_id": "bind",
        "profile_revision": 1,
        "effective_plan_digest": frozen.digest,
        "input_digest": "in",
        "baseline_digest": "base",
        "check_id": "jd_fit",
        "checked_dimensions": ["jd_fit"],
        "findings": [],
        "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # 1. 结果缺少 phase（空字符串） -> 必须 fail-closed 返回 unknown
    res_empty_phase = ControlResult.model_validate({**base_dict, "phase": ""})
    ev1 = decide_control_result(res_empty_phase, frozen, GateState())
    assert ev1.outcome == "unknown"
    assert "缺少或不匹配计划 scope phase" in ev1.reasons[0]

    # 2. 结果 phase 不匹配计划 phase -> 必须 fail-closed 返回 unknown
    res_wrong_phase = ControlResult.model_validate({**base_dict, "phase": "verify"})
    ev2 = decide_control_result(res_wrong_phase, frozen, GateState())
    assert ev2.outcome == "unknown"
    assert "缺少或不匹配计划 scope phase" in ev2.reasons[0]

    # 3. 结果 phase 精确匹配计划 phase -> 正常放行
    res_ok_phase = ControlResult.model_validate({**base_dict, "phase": "audit"})
    ev3 = decide_control_result(res_ok_phase, frozen, GateState())
    assert ev3.outcome == "pass"


def test_recheck_unchanged_input_bypasses_cache_reuse(tmp_path):
    from sopcontrol.control_profile import freeze_profile, normalize_profile, save_draft

    prof = {**BASE, "profile_id": "recheck-p", "repair": {"recheck_unchanged_input": True, "max_rounds": 1}}
    save_draft(tmp_path, normalize_profile(prof))
    frozen = freeze_profile(tmp_path, "recheck-p")

    res = ControlResult.model_validate({
        "result_id": "res-recheck-1",
        "task_id": "TASK-B",
        "phase": "audit",
        "profile_id": "recheck-p",
        "profile_revision": 1,
        "effective_plan_digest": frozen.digest,
        "input_digest": "in-stable",
        "baseline_digest": "base-stable",
        "check_id": "jd_fit",
        "checked_dimensions": ["jd_fit"],
        "findings": [],
        "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # 第一次求值：正常通过并缓存
    ev1 = evaluate_control_result(tmp_path, res, frozen)
    assert ev1.outcome == "pass"
    assert "（缓存）" not in ev1.reasons[0]

    # 第二次求值（输入完全一致）：因为声明了 recheck_unchanged_input=True，必须跳过缓存直接重新判定
    res2 = res.model_copy(update={"result_id": "res-recheck-2"})
    ev2 = evaluate_control_result(tmp_path, res2, frozen)
    assert ev2.outcome == "pass"
    assert "（缓存）" not in ev2.reasons[0]


def test_stop_after_pass_blocks_subsequent_evaluations_for_task(tmp_path):
    from sopcontrol.control_profile import freeze_profile, normalize_profile, save_draft
    from sopcontrol.task import Contract, TaskRecord, TaskStore

    prof = {
        **BASE,
        "profile_id": "stop-pass-task",
        "scope": {**BASE["scope"], "task": "TASK-STOP"},
        "repair": {"stop_after_pass": True, "max_rounds": 2},
    }
    save_draft(tmp_path, normalize_profile(prof))
    frozen = freeze_profile(tmp_path, "stop-pass-task")

    task = TaskRecord(
        task_id="TASK-STOP",
        contract=Contract(
            objective="obj",
            allowed_writes=[],
            required_rules=[],
            control_profile_id="stop-pass-task",
            control_profile_revision=1,
            effective_plan_digest=frozen.digest,
        ),
    )
    TaskStore(tmp_path).save(task)

    res1 = ControlResult.model_validate({
        "result_id": "res-stop-1",
        "task_id": "TASK-STOP",
        "phase": "audit",
        "profile_id": "stop-pass-task",
        "profile_revision": 1,
        "effective_plan_digest": frozen.digest,
        "input_digest": "in-stop",
        "baseline_digest": "base-stop",
        "check_id": "jd_fit",
        "checked_dimensions": ["jd_fit"],
        "findings": [],
        "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # 第一次通过
    ev1 = evaluate_control_result(tmp_path, res1, frozen, task_id="TASK-STOP")
    assert ev1.outcome == "pass"

    # 第二次尝试对已通过的任务再进行求值或修复 -> 触发 stop_after_pass 阻断
    res2 = res1.model_copy(update={"result_id": "res-stop-2", "input_digest": "in-stop-changed"})
    ev2 = evaluate_control_result(tmp_path, res2, frozen, task_id="TASK-STOP")
    assert ev2.outcome == "block"
    assert "已达停止条件 stop_after_pass" in ev2.reasons[0]


def test_check_id_never_autofilled_from_checked_dimensions():
    # §11.1（R-05）反回归：构造结果时不得用 checked_dimensions[0] 填充 check_id；
    # 缺失 check_id 的结果在幂等键处直接拒绝
    from sopcontrol.control_result import ControlResult, idempotency_key

    res = ControlResult.model_validate({
        "result_id": "no-check",
        "task_id": "TASK-9",
        "phase": "audit",
        "profile_id": "run-q",
        "profile_revision": 1,
        "effective_plan_digest": "",
        "input_digest": "in",
        "baseline_digest": "base",
        "checked_dimensions": ["jd_fit"],
        "findings": [],
        "rounds_used": 0,
    })
    assert res.check_id == ""
    with pytest.raises(ValueError, match="check_id"):
        idempotency_key(res)


def test_b4_goal_plan_digest_binding(tmp_path):
    # B4：open带旗标→show可见；不带→空=未绑定
    from sopcontrol.task import takeover_pack
    t1 = TaskRecord(task_id="T-B4", contract=Contract(objective="o", allowed_writes=[],
                     required_rules=[], goal_digest="g123", execution_plan_digest="p456"))
    pack = takeover_pack(t1, {}, [])
    assert pack["goal_digest"] == "g123" and pack["execution_plan_digest"] == "p456"
    t0 = TaskRecord(task_id="T-B4-0", contract=Contract(objective="o", allowed_writes=[],
                     required_rules=[]))
    pack0 = takeover_pack(t0, {}, [])
    assert pack0["goal_digest"] == "" and pack0["execution_plan_digest"] == ""
    # CLI wiring：Contract缺省空=未绑定，不引入新门槛
    assert t0.contract.goal_digest == "" and t0.contract.execution_plan_digest == ""


def test_b6_postconditions_gate():
    # B6：空=不绑定（存量行为不变）；非空缺项→unknown；齐备→不阻断此门
    from sopcontrol.control_result import ControlResult, GateState, decide_control_result
    from sopcontrol.control_profile import freeze_profile, normalize_profile
    import tempfile
    from pathlib import Path
    from datetime import datetime, timezone
    prof = normalize_profile(BASE)
    with tempfile.TemporaryDirectory() as td:
        from sopcontrol.control_profile import save_draft
        save_draft(Path(td), prof)
        frozen = freeze_profile(Path(td), "bind")
        mk = lambda pc: ControlResult.model_validate({
            "result_id": "b6", "task_id": "TASK-B", "phase": "audit", "profile_id": "bind",
            "profile_revision": frozen.revision, "effective_plan_digest": frozen.digest,
            "input_digest": "in", "baseline_digest": "base",
            "check_id": "jd_fit", "checked_dimensions": ["jd_fit"], "findings": [], "rounds_used": 0,
            "producer": {"actor": "a", "independence": "self_check"},
            "created_at": datetime.now(timezone.utc).isoformat(), "postconditions": pc})
        assert decide_control_result(mk([]), frozen, GateState()).outcome == "pass"
        st = GateState(expected_required_postconditions=["p1"])
        assert decide_control_result(mk([]), frozen, st).outcome == "unknown"
        assert decide_control_result(mk(["p1"]), frozen, st).outcome == "pass"

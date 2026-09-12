"""T-0094：任务契约绑定 + verify 门控（check_task_profile_gate / denial）。"""
from __future__ import annotations

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
        "result_id": "bind-r1", "task_id": "TASK-B", "profile_id": "bind",
        "profile_revision": 1, "effective_plan_digest": frozen.digest,
        "input_digest": "in", "baseline_digest": "base",
        "checked_dimensions": ["jd_fit"], "findings": [], "rounds_used": 0,
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
        "result_id": "bind-r2", "task_id": "TASK-B", "profile_id": "bind",
        "profile_revision": 1, "effective_plan_digest": frozen.digest,
        "input_digest": "in2", "baseline_digest": "base",
        "checked_dimensions": ["jd_fit"],
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
        "result_id": "bind-in", "task_id": "TASK-B", "profile_id": "bind",
        "profile_revision": 1, "effective_plan_digest": frozen.digest,
        "input_digest": "in-old", "baseline_digest": "base",
        "checked_dimensions": ["jd_fit"], "findings": [], "rounds_used": 0,
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

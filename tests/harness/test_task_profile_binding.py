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

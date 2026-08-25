"""场景8：弱模型漏 MUST 字段——确定性 schema 门，不靠自报。"""
from sopcontrol.cli import main
from sopcontrol.evals import run_capability_eval
from sopcontrol.task import Contract, TaskRecord, TaskStatus, evaluate_transition


def test_missing_must_field_rejected_on_submit():
    task = TaskRecord(
        task_id="TASK-0001",
        contract=Contract(
            objective="x",
            allowed_writes=["src/a.py"],
            required_rules=["R-1"],
            required_fields=["digest", "status"],
        ),
        status=TaskStatus.executing,
    )
    d = evaluate_transition(
        task, "submit",
        changed_paths=["src/a.py"],
        provided_fields={"digest": "abc"},
        known_rule_ids={"R-1"},
    )
    assert not d.allowed and "status" in d.reason

    d2 = evaluate_transition(
        task, "submit",
        changed_paths=["src/a.py"],
        provided_fields={"digest": "abc", "status": "ok"},
        known_rule_ids={"R-1"},
    )
    assert d2.allowed and d2.to_status == TaskStatus.verification_pending


def test_fragile_profile_forces_strict_schema(tmp_path):
    (tmp_path / ".sopcontrol" / "rules").mkdir(parents=True)
    (tmp_path / ".sopcontrol" / "rules" / "registry.yaml").write_text(
        "rules:\n"
        "- rule_id: R-1\n"
        "  statement: must\n"
        "  modality: MUST\n"
        "  status: accepted\n"
        "  scope: x\n"
        "  owner: t\n"
        "  risk: high\n"
        "  source: {type: manual_seed, ref: t}\n"
        "  consumer_markers: [x]\n",
        encoding="utf-8",
    )
    run_capability_eval(tmp_path, "weak-model", fixture="fragile")
    assert main([
        "task", "open", str(tmp_path),
        "--objective", "接线 R-1",
        "--allow", "src/a.py",
        "--require-rule", "R-1",
    ]) == 0
    # 未声明 require-field → accept 拒绝
    assert main(["task", "accept", "TASK-0001", str(tmp_path)]) == 0
    # wait - accept returns 0 even on reject? Check _task_decide - always returns 0
    # Look at printed state via show
    from sopcontrol.task import TaskStore
    task = TaskStore(tmp_path).load("TASK-0001")
    assert task.contract.strict_schema is True
    assert task.status == TaskStatus.contract_proposed  # accept 被拒

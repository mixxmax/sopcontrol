"""LP1 刀1/刀2：投影只保留可执行切片；blocked 裁决链衔接。"""
from __future__ import annotations

from pathlib import Path

from sopcontrol.model import Rule, RuleStatus, Modality, SourceRef
from sopcontrol.project import render_projection
from sopcontrol.task import (
    Contract,
    TaskRecord,
    TaskStatus,
    TaskStore,
    attach_resolution_links,
    tasks_for_projection,
    validate_resolution_targets,
)


def _rule() -> Rule:
    return Rule(
        rule_id="R-1",
        statement="must do x",
        modality=Modality.MUST,
        status=RuleStatus.accepted,
        source=SourceRef(type="document", ref="docs/a.md"),
        consumer_markers=["gate"],
    )


def _task(task_id: str, status: TaskStatus, **kwargs) -> TaskRecord:
    return TaskRecord(
        task_id=task_id,
        contract=Contract(objective=f"obj-{task_id}", allowed_writes=["src"], required_rules=["R-1"]),
        status=status,
        **kwargs,
    )


def test_tasks_for_projection_drops_delivered_and_resolved_blocked():
    tasks = [
        _task("TASK-0001", TaskStatus.delivered),
        _task("TASK-0002", TaskStatus.blocked, blocked_reason_code="policy_fail"),
        _task("TASK-0003", TaskStatus.executing),
        _task(
            "TASK-0004",
            TaskStatus.failed_unverified,
            blocked_reason_code="budget",
            superseded_by_task="TASK-0005",
        ),
        _task("TASK-0005", TaskStatus.contract_proposed, resolution_of=["TASK-0004"]),
    ]
    slice_ids = [t.task_id for t in tasks_for_projection(tasks)]
    assert slice_ids == ["TASK-0002", "TASK-0003", "TASK-0005"]


def test_render_projection_is_slice_not_full_history():
    tasks = [
        _task("TASK-0001", TaskStatus.delivered),
        _task("TASK-0002", TaskStatus.executing),
        _task("TASK-0099", TaskStatus.blocked, blocked_reason_code="trust_root"),
    ]
    text = render_projection([_rule()], tasks, refresh_hint="sopctl project all")
    assert "TASK-0002" in text
    assert "TASK-0001" not in text
    assert "当前可执行切片" in text
    assert "全量信息" not in text
    assert "TASK-0099" in text
    assert "sopctl task open --resolves TASK-0099" in text


def test_resolution_chain_links_and_hides_old_blocked(tmp_path: Path):
    root = tmp_path / "proj"
    (root / ".sopcontrol" / "tasks").mkdir(parents=True)
    store = TaskStore(root)
    old = _task("TASK-0001", TaskStatus.blocked, blocked_reason_code="policy_fail")
    store.save(old)

    new = _task("TASK-0002", TaskStatus.contract_proposed, resolution_of=["TASK-0001"])
    olds = validate_resolution_targets(store, new.task_id, ["TASK-0001"])
    store.save(new)
    attach_resolution_links(store, new, olds)

    reloaded_old = store.load("TASK-0001")
    reloaded_new = store.load("TASK-0002")
    assert reloaded_old.superseded_by_task == "TASK-0002"
    assert reloaded_new.resolution_of == ["TASK-0001"]

    slice_ids = [t.task_id for t in tasks_for_projection(store.list_all())]
    assert slice_ids == ["TASK-0002"]

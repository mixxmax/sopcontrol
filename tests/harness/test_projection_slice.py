"""LP1/LP3：投影切片、blocked 裁决链、长历史削薄、恢复协议。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sopcontrol.model import Rule, RuleStatus, Modality, SourceRef
from sopcontrol.project import check_projections, render_projection, write_all_projections
from sopcontrol.registry import Registry
from sopcontrol.task import (
    Contract,
    TaskRecord,
    TaskStatus,
    TaskStore,
    attach_resolution_links,
    select_projection_tasks,
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
    assert "当前链头" in text
    assert "新会话恢复" in text
    assert "全量信息" not in text
    assert "TASK-0099" in text
    assert "sopctl task open --resolves TASK-0099" in text
    assert "为何在切片" in text
    assert "本切片摘要" in text


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


def test_select_folds_verified_and_caps_heads():
    base = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    tasks = []
    for i in range(1, 21):
        tasks.append(_task(f"TASK-{i:04d}", TaskStatus.delivered))
    tasks.append(_task("TASK-0021", TaskStatus.verified))
    tasks.append(_task("TASK-0022", TaskStatus.verified))
    # 6 active + 1 blocked → with max_heads=5, one active omitted
    for i in range(23, 29):
        tasks.append(
            _task(
                f"TASK-{i:04d}",
                TaskStatus.executing,
                updated_at=base + timedelta(minutes=i),
            )
        )
    tasks.append(
        _task(
            "TASK-0099",
            TaskStatus.blocked,
            blocked_reason_code="policy_fail",
            updated_at=base,
        )
    )

    selected = select_projection_tasks(tasks, max_heads=5)
    assert selected.folded_verified == 2
    assert len(selected.heads) == 5
    assert all(t.status != TaskStatus.delivered for t in selected.heads)
    assert all(t.status != TaskStatus.verified for t in selected.heads)
    assert selected.omitted_active >= 1
    assert selected.digest
    head_ids = {t.task_id for t in selected.heads}
    # 最近更新的 executing 应优先于更早的 blocked
    assert "TASK-0028" in head_ids
    assert "TASK-0099" not in head_ids or len(selected.heads) == 5


def test_long_history_projection_stays_short_and_actionable():
    """≥20 delivered + 1 executing + 1 unresolved blocked → 投影仍短且可决策。"""
    tasks = [_task(f"TASK-{i:04d}", TaskStatus.delivered) for i in range(1, 25)]
    tasks.append(_task("TASK-0100", TaskStatus.executing))
    tasks.append(
        _task("TASK-0101", TaskStatus.blocked, blocked_reason_code="evidence_gap")
    )
    text = render_projection([_rule()], tasks, refresh_hint="sopctl project all", max_heads=5)
    assert "TASK-0100" in text
    assert "TASK-0101" in text
    for i in range(1, 25):
        assert f"TASK-{i:04d}" not in text
    assert "新会话恢复" in text
    assert "合法动作" in text
    assert "本切片摘要" in text
    assert "为何在切片" in text
    # 整节应保持短：远小于「逐条列出 24+ 历史」的体量
    assert text.count("\n") < 80


def test_write_and_check_share_slice_digest(tmp_path: Path):
    root = tmp_path / "proj"
    (root / ".sopcontrol" / "rules").mkdir(parents=True)
    (root / ".sopcontrol" / "tasks").mkdir(parents=True)
    Registry(root / ".sopcontrol" / "rules" / "registry.yaml").save([_rule()])
    store = TaskStore(root)
    store.save(_task("TASK-0001", TaskStatus.executing))
    for i in range(2, 22):
        store.save(_task(f"TASK-{i:04d}", TaskStatus.delivered))

    write_all_projections(root)
    reports = {r["path"]: r for r in check_projections(root)}
    assert reports["AGENTS.md"]["status"] == "ok"
    assert reports["CLAUDE.md"]["status"] == "ok"
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "新会话恢复" in agents
    assert "TASK-0001" in agents
    assert "TASK-0002" not in agents  # delivered 不进
    assert "本切片摘要" in agents

"""LP4：项目编年 — 换会话可知何以至此；事件重放可核对。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sopcontrol.chronicle import (
    check_reconstruction,
    journey_lines,
    load_project_events,
    write_view_snapshot,
)
from sopcontrol.cli import main
from sopcontrol.model import Modality, Rule, RuleStatus, SourceRef
from sopcontrol.project import render_projection, write_all_projections
from sopcontrol.registry import Registry
from sopcontrol.task import Contract, TaskRecord, TaskStatus, TaskStore, evaluate_transition


def _rule(rule_id: str = "LIFE-001") -> Rule:
    return Rule(
        rule_id=rule_id,
        statement="must keep gateway",
        modality=Modality.MUST,
        status=RuleStatus.proposed,
        source=SourceRef(type="manual_seed", ref="tests"),
        consumer_markers=["gateway"],
    )


def _init_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / ".sopcontrol" / "rules").mkdir(parents=True)
    (root / ".sopcontrol" / "tasks").mkdir(parents=True)
    Registry(root / ".sopcontrol" / "rules" / "registry.yaml").save([])
    return root


def test_rule_lifecycle_and_task_appear_in_chronicle(tmp_path, monkeypatch):
    root = _init_project(tmp_path)
    registry = Registry(root / ".sopcontrol" / "rules" / "registry.yaml")
    registry.add(_rule())
    registry.transition("LIFE-001", RuleStatus.accepted)

    now = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    until = now + timedelta(hours=2)
    monkeypatch.setattr("sopcontrol.registry.utcnow", lambda: now)
    preview = registry.lifecycle_preview(
        "LIFE-001",
        action="suspend",
        reason="维护窗口",
        actor="human-reviewer",
        until=until,
    )
    registry.confirm_lifecycle(
        "LIFE-001",
        action="suspend",
        reason="维护窗口",
        actor="human-reviewer",
        preview_id=preview["preview_id"],
        until=until,
    )

    store = TaskStore(root)
    task = TaskRecord(
        task_id="TASK-0001",
        contract=Contract(
            objective="wire gateway",
            allowed_writes=["src"],
            required_rules=["LIFE-001"],
        ),
    )
    store.save(task)
    decision = evaluate_transition(task, "accept", known_rule_ids={"LIFE-001"})
    store.apply(task, decision, "accept")

    loaded = load_project_events(root)
    kinds = [e.kind for e in loaded.events]
    assert "rule.add" in kinds
    assert "rule.transition" in kinds
    assert "rule.lifecycle" in kinds
    assert "task.transition" in kinds
    assert loaded.integrity_ok

    report = check_reconstruction(root)
    assert report.ok
    assert report.event_count >= 4

    text = "\n".join(journey_lines(root, limit=10))
    assert "LIFE-001" in text
    assert "suspend" in text or "TASK-0001" in text


def test_projection_includes_journey_when_root_given(tmp_path, monkeypatch):
    root = _init_project(tmp_path)
    registry = Registry(root / ".sopcontrol" / "rules" / "registry.yaml")
    rule = _rule()
    rule.status = RuleStatus.accepted
    registry.add(rule)

    section = render_projection(
        registry.load(),
        [],
        refresh_hint="sopctl project all",
        project_root=root,
    )
    assert "何以至此" in section
    assert "sopctl chronicle" in section

    write_all_projections(root)
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "何以至此" in agents


def test_chronicle_cli_check_and_snapshot(tmp_path):
    root = _init_project(tmp_path)
    Registry(root / ".sopcontrol" / "rules" / "registry.yaml").add(_rule())
    assert main(["chronicle", "show", str(root)]) == 0
    assert main(["chronicle", "check", str(root)]) == 0
    assert main(["chronicle", "snapshot", str(root)]) == 0
    assert (root / ".sopcontrol" / "evidence" / "view-snapshot.yaml").exists()
    snap_events = load_project_events(root)
    assert any(e.kind == "view.snapshot" for e in snap_events.events)


def test_ledger_compact_does_not_wipe_chronicle(tmp_path):
    root = _init_project(tmp_path)
    Registry(root / ".sopcontrol" / "rules" / "registry.yaml").add(_rule())
    before = len(load_project_events(root).events)
    from sopcontrol.ledger import Ledger
    from sopcontrol.model import Evidence

    ledger = Ledger(root / ".sopcontrol" / "evidence" / "ledger.jsonl")
    ledger.replace_snapshot([], [])
    after = load_project_events(root)
    assert len(after.events) == before
    assert after.integrity_ok

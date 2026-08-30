"""第二批：被动能力事件只复用既有结果，不扫描、不调权。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sopcontrol.capability import FIXTURES, build_profile, effective_control_knobs
from sopcontrol.capability_events import (
    MAX_CAPABILITY_EVENTS,
    CapabilityEvent,
    append_capability_event,
    capability_event_path,
    load_capability_events,
    replay_capability_events,
)
from sopcontrol.cli import main


def _event(**overrides) -> CapabilityEvent:
    data = {
        "kind": "task.transition",
        "subject": "TASK-0001",
        "outcome": "denied",
        "model": "model-a",
        "tier": "unknown",
        "detail": {"action": "submit", "from_status": "executing"},
    }
    data.update(overrides)
    return CapabilityEvent(**data)


def _write_registry(root: Path) -> None:
    rules = root / ".sopcontrol" / "rules"
    rules.mkdir(parents=True)
    (rules / "registry.yaml").write_text(
        """rules:
- rule_id: R-1
  statement: 必须接线
  modality: MUST
  status: accepted
  scope: x
  owner: test
  risk: high
  source:
    type: manual_seed
    ref: test
  consumer_markers: [x]
""",
        encoding="utf-8",
    )


def test_event_id_is_content_addressed_and_timestamp_free():
    first = _event()
    second = _event()
    assert first.event_id == second.event_id
    assert first.observed_at != second.observed_at

    changed = _event(outcome="allowed")
    assert changed.event_id != first.event_id


def test_append_deduplicates_and_replay_is_deterministic(tmp_path):
    event = _event()
    assert append_capability_event(tmp_path, event) is True
    assert append_capability_event(tmp_path, event) is False

    loaded = load_capability_events(tmp_path)
    assert [item.event_id for item in loaded] == [event.event_id]
    assert replay_capability_events(loaded) == replay_capability_events(list(reversed(loaded)))
    summary = replay_capability_events(loaded)
    assert summary["event_count"] == 1
    assert summary["by_kind"] == {"task.transition": 1}
    assert summary["by_outcome"] == {"denied": 1}
    assert summary["by_model"] == {"model-a": 1}
    assert summary["by_tier"] == {"unknown": 1}


def test_log_is_bounded_and_malformed_lines_are_ignored(tmp_path):
    path = capability_event_path(tmp_path)
    for index in range(MAX_CAPABILITY_EVENTS + 7):
        append_capability_event(
            tmp_path,
            _event(subject=f"TASK-{index:04d}"),
        )
    assert len(load_capability_events(tmp_path)) == MAX_CAPABILITY_EVENTS

    with path.open("a", encoding="utf-8") as handle:
        handle.write("not-json\n")
    assert len(load_capability_events(tmp_path)) == MAX_CAPABILITY_EVENTS


def test_append_failure_is_silent(tmp_path, monkeypatch):
    def fail_open(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", fail_open)
    assert append_capability_event(tmp_path, _event()) is False


def test_event_path_does_not_scan_or_spawn(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("事件采集不得扫描仓库")

    monkeypatch.setattr(Path, "glob", forbidden)
    monkeypatch.setattr(Path, "rglob", forbidden)
    assert append_capability_event(tmp_path, _event()) is True


def test_event_log_cannot_change_effective_knobs(tmp_path):
    profile = build_profile("model-a", FIXTURES["strong"], source="fixture:strong", at="t")
    before = effective_control_knobs(profile, current_model="model-a")
    append_capability_event(
        tmp_path,
        _event(kind="task.completed", outcome="success", tier="strong"),
    )
    after = effective_control_knobs(profile, current_model="model-a")
    assert before == after
    assert after.tier == "unknown"

    capability_source = Path("sopcontrol/capability.py").read_text(encoding="utf-8")
    assert "capability_events" not in capability_source


def test_real_cli_paths_emit_objective_events(tmp_path):
    _write_registry(tmp_path)

    assert main([
        "task", "open", str(tmp_path),
        "--model", "unprofiled-model",
        "--objective", "接线 R-1",
        "--allow", "src/a.py",
        "--require-rule", "R-1",
        "--require-field", "status",
    ]) == 0
    assert main(["task", "accept", "TASK-0001", str(tmp_path)]) == 0
    assert main([
        "task", "submit", "TASK-0001", str(tmp_path),
        "--changed", "src/outside.py", "--field", "status=ok",
    ]) == 0

    events = load_capability_events(tmp_path)
    opened = [event for event in events if event.kind == "task.open"]
    transitions = [event for event in events if event.kind == "task.transition"]
    assert len(opened) == 1
    assert opened[0].model == "unprofiled-model"
    assert opened[0].tier == "unknown"
    assert opened[0].detail["write_granularity"] == "file"
    assert any(
        event.detail.get("action") == "accept" and event.outcome == "allowed"
        for event in transitions
    )
    assert any(
        event.detail.get("action") == "submit" and event.outcome == "denied"
        for event in transitions
    )


def test_harness_decision_emits_event_without_new_decision_work(tmp_path):
    payload = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "git commit --no-verify -m x"},
    })
    assert main(["harness-check", "--payload", payload, str(tmp_path)]) == 0
    events = load_capability_events(tmp_path)
    guard = [event for event in events if event.kind == "guard.decision"]
    assert len(guard) == 1
    assert guard[0].outcome == "deny"
    assert "GUARD-NO-VERIFY" in guard[0].detail["rule_ids"]


def test_gate_result_emits_event(tmp_path, monkeypatch):
    from sopcontrol import cli_common

    class Report:
        verdicts = []

    monkeypatch.setattr(cli_common, "run_audit", lambda *args, **kwargs: Report())
    monkeypatch.setattr(cli_common.Ledger, "verify", lambda self: True)
    assert cli_common.run_gate(tmp_path) == 0
    events = load_capability_events(tmp_path)
    gate = [event for event in events if event.kind == "gate.result"]
    assert len(gate) == 1
    assert gate[0].outcome == "pass"
    assert gate[0].detail == {"fails": 0, "gaps": 0, "ledger_tampered": False}

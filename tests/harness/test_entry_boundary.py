"""WP-C1：入口边界——损坏账本fail-closed、宿主声明写不放行、分harness验收。"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

from sopcontrol.action_plane import evaluate_payload
from sopcontrol.cli import main
from sopcontrol.model import (
    ActivationSelector,
    Modality,
    Rule,
    RuleLifecycleEvent,
    RuleStatus,
    SourceRef,
)
from sopcontrol.registry import Registry


def _git_init(path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True, timeout=30)


def _corrupt_task_ledger(work) -> None:
    tasks = work / ".sopcontrol" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / "TASK-0001.yaml").write_text("task_id: [unclosed\n", encoding="utf-8")


def _check(work, payload, monkey_cwd=None):
    import json as _json

    out = main(["harness-check", str(work), "--payload", _json.dumps(payload)])
    return out


def _compiled_rule(
    rule_id: str,
    *,
    modality: Modality = Modality.MUST,
    actions: tuple[str, ...] = ("materials.audit",),
    scope_paths: tuple[str, ...] = (),
) -> Rule:
    now = datetime.now(timezone.utc)
    lifecycle_events = []
    if scope_paths:
        lifecycle_events = [RuleLifecycleEvent(
            action="narrow",
            actor="test",
            reason="production entry test scope",
            at=now,
            preview_id=f"pv-{rule_id}",
            revision=1,
            before_scope=[],
            after_scope=list(scope_paths),
        )]
    return Rule(
        rule_id=rule_id,
        statement=f"动态 SOP {rule_id}",
        modality=modality,
        status=RuleStatus.compiled,
        rule_class="dynamic_sop",
        activation=ActivationSelector(
            products=["sopcontrol"], actions=list(actions), phases=["admission"],
        ),
        scope_paths=list(scope_paths),
        lifecycle_revision=1 if lifecycle_events else 0,
        lifecycle_events=lifecycle_events,
        effective_since=now if lifecycle_events else None,
        source=SourceRef(ref="test:entry-boundary"),
        consumer_markers=["harness.admission"],
        accepted_at=now,
        compiled_at=now,
        compile_digest=f"compile-{rule_id}",
        compile_tool="test:dynamic-sop-compile",
    )


def _add_rules(work, *rules: Rule) -> None:
    registry = Registry(work / ".sopcontrol" / "rules" / "registry.yaml")
    registry.save(registry.load() + list(rules))


def _activity_gate(work):
    from sopcontrol.activity_log import load_activity

    return next(
        event for event in reversed(load_activity(work).events)
        if event.event_type == "gate_evaluated"
    )


def test_corrupt_ledger_write_escalates_to_ask(tmp_path, capsys):
    work = tmp_path / "p"
    work.mkdir()
    _git_init(work)
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    _corrupt_task_ledger(work)
    payload = {"tool_name": "Write",
               "tool_input": {"file_path": "notes.txt", "content": "hi"}}
    assert _check(work, payload) == 0
    decision = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask"
    assert "任务账本不可读" in decision["permissionDecisionReason"]


def test_corrupt_ledger_read_stays_observe(tmp_path, capsys):
    work = tmp_path / "p"
    work.mkdir()
    _git_init(work)
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    _corrupt_task_ledger(work)
    payload = {"tool_name": "Read", "tool_input": {"file_path": "README.md"}}
    assert _check(work, payload) == 0
    decision = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    # 只读不泛阻断：observe→allow，但事件可追踪
    assert decision["permissionDecision"] == "allow"


def test_unknown_tool_claimed_write_not_allowed():
    for harness in ("claude", "opencode", "codex"):
        decision = evaluate_payload(
            {"tool_name": "blaster9000",
             "tool_input": {"path": "/tmp/x"},
             "claimed_side_effects": ["external_write"]},
            harness=harness)
        assert decision.decision == "ask", harness
        assert "自称受控写入口" in decision.reason
        assert decision.gap.startswith("unrecognized_tool:")


def test_unknown_tool_without_claim_stays_observe():
    for harness in ("claude", "opencode", "codex"):
        decision = evaluate_payload(
            {"tool_name": "quietpeeker", "tool_input": {"q": "x"}},
            harness=harness)
        assert decision.decision == "observe", harness
        assert decision.gap.startswith("unrecognized_tool:")


def test_mcp_tool_claimed_write_not_allowed():
    """mcp 面同样：自称写入口不得 observe→allow；无声明仍观察。"""
    for harness in ("claude", "opencode", "codex"):
        claimed = evaluate_payload(
            {"tool_name": "mcp__weird__blast", "tool_input": {"path": "/tmp/x"},
             "claimed_side_effects": ["external_write"]},
            harness=harness)
        assert claimed.decision == "ask", harness
        plain = evaluate_payload(
            {"tool_name": "mcp__weird__blast", "tool_input": {"path": "/tmp/x"}},
            harness=harness)
        assert plain.decision == "observe", harness


def test_claimed_write_cli_end_to_end(tmp_path, capsys, monkeypatch):
    work = tmp_path / "p"
    work.mkdir()
    _git_init(work)
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    monkeypatch.chdir(work)
    payload = {"tool_name": "blaster9000",
               "tool_input": {"path": "/tmp/x"},
               "claimed_side_effects": ["external_write"]}
    assert main(["harness-check", str(work), "--payload",
                 json.dumps(payload)]) == 0
    decision = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask"


def test_missing_command_target_stays_traceable_observe():
    """缺字段载荷：可追踪 observe（gap 留痕），不静默消失、不泛阻断。"""
    for harness in ("claude", "opencode", "codex"):
        decision = evaluate_payload({"tool_name": "", "tool_input": {}},
                                    harness=harness)
        assert decision.decision == "observe", harness
        assert decision.gap, harness


def test_formal_harness_entry_selects_compiled_dynamic_rule(tmp_path, capsys):
    """The CLI admission, not the selector unit, consumes the effective rule."""
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    _add_rules(work, _compiled_rule("DYN-HARNESS-001"))

    payload = {
        "tool_name": "Read",
        "product": "sopcontrol",
        "action": "materials.audit",
        "phase": "admission",
        "task_id": "TASK-ENTRY-1",
        "tool_input": {"file_path": "docs/evidence.md"},
    }
    assert _check(work, payload) == 0
    wire = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    gate = _activity_gate(work)

    assert wire["permissionDecision"] == "allow"  # observe on the wire
    assert gate.decision == "observe"
    assert "DYN-HARNESS-001" in gate.rule_ids
    assert gate.detail["selection_evidence"].startswith("sel-")
    assert gate.task_id == "TASK-ENTRY-1"


def test_formal_harness_entry_explains_selector_mismatch(tmp_path, capsys):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    _add_rules(work, _compiled_rule("DYN-HARNESS-MISMATCH"))

    payload = {
        "tool_name": "Read",
        "product": "sopcontrol",
        "action": "materials.other",
        "phase": "admission",
        "tool_input": {"file_path": "docs/evidence.md"},
    }
    assert _check(work, payload) == 0
    wire = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    gate = _activity_gate(work)

    assert wire["permissionDecision"] == "allow"
    assert "DYN-HARNESS-MISMATCH" not in gate.rule_ids
    assert "本次未选择" in wire["permissionDecisionReason"]
    assert "action=materials.other" in wire["permissionDecisionReason"]
    assert gate.detail["selection_evidence"].startswith("sel-")


def test_formal_harness_entry_conflict_returns_ask(tmp_path, capsys):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    _add_rules(
        work,
        _compiled_rule("DYN-HARNESS-MUST"),
        _compiled_rule(
            "DYN-HARNESS-MUST-NOT",
            modality=Modality.MUST_NOT,
        ),
    )

    payload = {
        "tool_name": "Read",
        "product": "sopcontrol",
        "action": "materials.audit",
        "phase": "admission",
        "tool_input": {"file_path": "docs/evidence.md"},
    }
    assert _check(work, payload) == 0
    wire = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    gate = _activity_gate(work)

    assert wire["permissionDecision"] == "ask"
    assert gate.decision == "ask"
    assert set(gate.rule_ids) == {"DYN-HARNESS-MUST", "DYN-HARNESS-MUST-NOT"}
    assert gate.detail["selection_evidence"].startswith("sel-")
    assert "需用户决定" in wire["permissionDecisionReason"]

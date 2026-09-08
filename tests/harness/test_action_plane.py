"""Phase B: Action Plane — envelope equivalence, observe unknowns, no silent drop."""
from __future__ import annotations

import builtins
import json

import pytest

from sopcontrol.action_classifier import classify_tool, normalize_tool_name
from sopcontrol.action_plane import (
    build_envelope,
    commit_action_result,
    equivalent_envelopes,
    evaluate_action,
    evaluate_payload,
)
from sopcontrol.cli import main
from sopcontrol.events import load_events
from sopcontrol.harness import check_tool_call


def test_claude_and_opencode_write_envelopes_equivalent():
    claude = build_envelope(
        {"tool_name": "Write", "tool_input": {"file_path": "src/a.py", "content": "SECRET"}},
        harness="claude",
    )
    opencode = build_envelope(
        {"tool_name": "write", "tool_input": {"filePath": "src/a.py", "content": "OTHER"}},
        harness="opencode",
    )
    assert claude.surface == opencode.surface == "filesystem_write"
    assert claude.target == opencode.target == "src/a.py"
    assert equivalent_envelopes(claude, opencode)
    # bodies must not appear in summary
    assert "SECRET" not in json.dumps(claude.summary)
    assert "content_bytes" in claude.summary


def test_unknown_tool_is_observe_not_silent():
    d = evaluate_payload({"tool_name": "WeirdToolX", "tool_input": {"q": "1"}})
    assert d.decision == "observe"
    assert d.surface == "unknown"
    assert "WeirdToolX" in d.gap or "WeirdToolX" in d.reason


def test_read_search_browser_mcp_are_observe():
    cases = [
        ("Read", {"file_path": "README.md"}, "filesystem_read"),
        ("Glob", {"pattern": "**/*.py"}, "search"),
        ("WebFetch", {"url": "https://example.com"}, "network"),
        ("browser_navigate", {"url": "https://x"}, "browser"),
        ("mcp__fs__list", {"path": "."}, "mcp"),
    ]
    for tool, inp, surface in cases:
        d = evaluate_payload({"tool_name": tool, "tool_input": inp})
        assert d.decision == "observe", tool
        assert d.surface == surface, tool


def test_check_tool_call_wrapper_maps_observe_to_allow():
    d = check_tool_call({"tool_name": "Read", "tool_input": {"file_path": "a.py"}})
    assert d.permissionDecision == "allow"
    assert "观察" in d.reason or "read" in d.reason.lower() or "filesystem_read" in d.reason


def test_existing_guards_still_via_action_plane():
    assert check_tool_call(
        {"tool_name": "Bash", "tool_input": {"command": "git push --no-verify"}}
    ).permissionDecision == "deny"
    assert check_tool_call(
        {"tool_name": "edit", "tool_input": {"filePath": ".sopcontrol/rules/registry.yaml"}}
    ).permissionDecision == "deny"


def test_evaluate_action_is_pure(monkeypatch):
    def no_open(*a, **k):
        raise AssertionError("Action Plane evaluate must not do I/O")

    monkeypatch.setattr(builtins, "open", no_open)
    env = build_envelope({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    d = evaluate_action(env, tool_input={"command": "ls"})
    assert d.decision == "allow"


def test_harness_check_records_unknown_tool_event(tmp_path, capsys):
    assert main(["init", str(tmp_path)]) == 0
    capsys.readouterr()  # drop init banners
    payload = json.dumps({"tool_name": "TotallyUnknown", "tool_input": {"x": 1}})
    assert main(["harness-check", str(tmp_path), "--payload", payload]) == 0
    captured = capsys.readouterr().out.strip()
    # stdout may include trailing noise; take the JSON object line
    json_line = next(ln for ln in captured.splitlines() if ln.strip().startswith("{"))
    out = json.loads(json_line)
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    events = load_events(tmp_path)
    assert any(e.outcome == "observe" for e in events), [e.model_dump() for e in events[-5:]]
    assert any(
        "unrecognized_tool" in str((e.detail or {}).get("gap", ""))
        or e.action == "totallyunknown"
        for e in events
    )


def test_normalize_tool_names():
    assert normalize_tool_name("Bash") == "bash"
    assert normalize_tool_name("Write") == "write"
    assert classify_tool("mcp__browser__click", {})[0] == "mcp"

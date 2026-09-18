"""WP-C1：入口边界——损坏账本fail-closed、宿主声明写不放行、分harness验收。"""
from __future__ import annotations

import json
import subprocess

from sopcontrol.action_plane import evaluate_payload
from sopcontrol.cli import main


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

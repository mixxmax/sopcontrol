"""B4 harness 适配测试：决策纯函数契约、fail-closed、安装器合并不覆盖。"""
import json

from sopcontrol.cli import main
from sopcontrol.harness import HookDecision, check_tool_call


def call(tool, **tool_input):
    return check_tool_call({"tool_name": tool, "tool_input": tool_input})


def test_agent_cannot_write_controller_files():
    d = call("Write", file_path="proj/.sopcontrol/rules/registry.yaml", content="rules: []")
    assert d.permissionDecision == "deny" and "sopctl" in d.reason

    d = call("Edit", file_path=".sopcontrol/evidence/ledger.jsonl", old_string="a", new_string="b")
    assert d.permissionDecision == "deny"


def test_normal_write_allowed():
    assert call("Write", file_path="src/app.py", content="x").permissionDecision == "allow"


def test_no_verify_always_denied():
    d = call("Bash", command="git push --no-verify origin main")
    assert d.permissionDecision == "deny" and "R6" in d.reason
    d = call("Bash", command="git commit --no-verify -m x")
    assert d.permissionDecision == "deny"


def test_controller_dir_via_bash_requires_sopctl():
    d = call("Bash", command="echo 'rules: []' > .sopcontrol/rules/registry.yaml")
    assert d.permissionDecision == "deny"
    assert call("Bash", command="sopctl task submit TASK-0001 --changed src/a.py").permissionDecision == "allow"


def test_git_push_follows_gate_status():
    d = call("Bash", command="git push origin main")  # 无门上下文 → fail-closed
    assert d.permissionDecision == "deny"
    d = check_tool_call({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}, "block")
    assert d.permissionDecision == "deny"
    d = check_tool_call({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}, "warn")
    assert d.permissionDecision == "ask"
    d = check_tool_call({"tool_name": "Bash", "tool_input": {"command": "cd /x && git push"}}, "clean")
    assert d.permissionDecision == "allow"


def test_unrelated_bash_and_tools_are_observed_not_blocked():
    assert call("Bash", command="pytest -q").permissionDecision == "allow"
    assert call("Read", file_path=".sopcontrol/evidence/ledger.jsonl").permissionDecision == "allow"


def test_claude_payload_shape():
    payload = call("Write", file_path=".sopcontrol/x", content="y").claude_payload()
    assert payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_installer_merges_without_clobber(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}}), encoding="utf-8")

    assert main(["hook", "claude", str(tmp_path)]) == 0
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["permissions"]["allow"] == ["Bash(ls)"]  # 既有配置未被破坏
    pre = data["hooks"]["PreToolUse"]
    assert any("sopcontrol.cli harness check" in h["command"] for e in pre for h in e["hooks"])

    assert main(["hook", "claude", str(tmp_path)]) == 0  # 幂等
    data2 = json.loads(settings.read_text(encoding="utf-8"))
    n = sum(
        "sopcontrol.cli" in h["command"]
        for e in data2["hooks"]["PreToolUse"] for h in e["hooks"]
    )
    assert n == 1

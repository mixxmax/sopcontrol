"""B4 harness 适配测试：决策纯函数契约、fail-closed、安装器合并不覆盖。"""
import json
import re

from sopcontrol.cli import build_parser, main
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


def test_uninstalling_own_leash_is_denied():
    d = call("Write", file_path=".opencode/plugins/sopcontrol.js", content="export const X = 1")
    assert d.permissionDecision == "deny" and "人工" in d.reason
    d = call("Edit", file_path="proj/.claude/settings.json", old_string="a", new_string="b")
    assert d.permissionDecision == "deny"
    d = call("Bash", command="rm .opencode/plugins/sopcontrol.js")
    assert d.permissionDecision == "deny"
    assert call("Bash", command="sopctl doctor").permissionDecision == "allow"


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
    assert any("sopcontrol.cli" in h["command"] for e in pre for h in e["hooks"])

    assert main(["hook", "claude", str(tmp_path)]) == 0  # 幂等
    data2 = json.loads(settings.read_text(encoding="utf-8"))
    n = sum(
        "sopcontrol.cli" in h["command"]
        for e in data2["hooks"]["PreToolUse"] for h in e["hooks"]
    )
    assert n == 1


def _parser_subcommands() -> set[str]:
    """真 parser 认识的子命令名，而不是测试里再抄一份字面量。"""
    import argparse

    for action in build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("build_parser 没有子命令，安装器校验失去意义")


def test_installed_hook_commands_are_real_subcommands(tmp_path):
    """安装器写进配置的子命令名必须是 parser 真的认识的那个。

    这条测试存在的原因是它抓到过真 bug：安装器写的是两段 "harness check"，
    parser 只认 "harness-check"，argparse 以 exit 2 退出、钩子永远拿不到决策。
    旧测试断言的是同一个错字符串，于是「测试全绿 + 治理完全没生效」并存了很久
    （手册 16.4 治理幻觉）。断言对象换成真 parser 后，字面量再漂移就会红。
    """
    valid = _parser_subcommands()

    assert main(["hook", "claude", str(tmp_path)]) == 0
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [
        h["command"]
        for e in settings["hooks"]["PreToolUse"]
        for h in e["hooks"]
        if "sopcontrol.cli" in h["command"]
    ]
    assert commands, "claude 安装器没写入任何 sopcontrol 命令"

    assert main(["hook", "opencode", str(tmp_path)]) == 0
    plugin = (tmp_path / ".opencode" / "plugins" / "sopcontrol.js").read_text(encoding="utf-8")
    # 插件里是 JS 数组字面量：["-m", "sopcontrol.cli", "<sub>", ...]
    commands += [m.replace('"', " ").replace(",", " ") for m in re.findall(
        r'"sopcontrol\.cli"\s*,\s*"[^"]+"', plugin
    )]
    assert len(commands) >= 2, "opencode 插件没写入 sopcontrol 调用"

    for cmd in commands:
        tokens = cmd.split()
        i = next(n for n, t in enumerate(tokens) if "sopcontrol.cli" in t)
        sub = tokens[i + 1]
        assert sub in valid, f"安装器写的子命令 {sub!r} 不在 parser 中；候选: {sorted(valid)}"

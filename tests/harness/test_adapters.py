"""B4 适配层测试：工具名归一、--payload 入口、opencode 安装器、AGENTS.md 投影。"""
import json

from sopcontrol.cli import main
from sopcontrol.harness import check_tool_call
from sopcontrol.project import SECTION_START, SECTION_END


def test_tool_names_normalized_across_harnesses():
    d = check_tool_call({"tool_name": "bash", "tool_input": {"command": "git push --no-verify"}})
    assert d.permissionDecision == "deny"
    d = check_tool_call({"tool_name": "edit", "tool_input": {"filePath": "x/.sopcontrol/rules/registry.yaml"}})
    assert d.permissionDecision == "deny"
    d = check_tool_call({"tool_name": "Bash", "tool_input": {"command": "pytest"}})
    assert d.permissionDecision == "allow"


def test_harness_check_payload_flag(tmp_path, capsys):
    payload = json.dumps({"tool_name": "bash", "tool_input": {"command": "echo hi > .sopcontrol/x"}})
    assert main(["harness-check", str(tmp_path), "--payload", payload]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_opencode_plugin_installer(tmp_path):
    assert main(["hook", "opencode", str(tmp_path)]) == 0
    plugin = tmp_path / ".opencode" / "plugins" / "sopcontrol.js"
    content = plugin.read_text(encoding="utf-8")
    assert "sopcontrol-hook v1" in content and "tool.execute.before" in content
    assert str(tmp_path) in content  # 绑定安装时的项目绝对路径

    assert main(["hook", "opencode", str(tmp_path)]) == 0  # 幂等
    plugin.write_text("// 别人的插件\n")
    assert main(["hook", "opencode", str(tmp_path)]) == 2  # 拒绝覆盖
    assert "别人的插件" in plugin.read_text(encoding="utf-8")

    profile = tmp_path / ".sopcontrol" / "harness-profile.yaml"
    assert profile.exists()


def test_agents_projection_merges_only_own_section(tmp_path):
    import shutil

    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/ci-deploy", work)
    agents = work / "AGENTS.md"
    agents.write_text("# 项目说明\n\n原有内容，不得被投影破坏。\n", encoding="utf-8")

    assert main(["project", "codex", str(work)]) == 0
    text = agents.read_text(encoding="utf-8")
    assert "原有内容" in text and SECTION_START in text
    assert "DEPLOY-001" in text  # accepted 硬规则被投影

    # 规则变化后重跑：只刷新自身小节，其余内容原样
    agents.write_text(text.replace("原有内容", "原有内容已更新"), encoding="utf-8")
    assert main(["project", "codex", str(work)]) == 0
    text2 = agents.read_text(encoding="utf-8")
    assert "原有内容已更新" in text2
    assert text2.count(SECTION_START) == 1 and text2.count(SECTION_END) == 1


def test_project_all_writes_agents_and_claude(tmp_path):
    import shutil

    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/ci-deploy", work)
    (work / "CLAUDE.md").write_text("# 原有 Claude 说明\n", encoding="utf-8")

    assert main(["project", "all", str(work)]) == 0
    agents = (work / "AGENTS.md").read_text(encoding="utf-8")
    claude = (work / "CLAUDE.md").read_text(encoding="utf-8")
    assert "DEPLOY-001" in agents and SECTION_START in agents
    assert "DEPLOY-001" in claude and "原有 Claude 说明" in claude
    assert "discuss_only" in claude or "只讨论" in claude

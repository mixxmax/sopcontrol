"""场景12：无 tool hook 的 harness 只能靠 Git/CI/wrap 终态控制。"""
import shutil

from sopcontrol.cli import main
from sopcontrol.harness import HARNESS_PROFILES, check_tool_call


def test_scenario12_no_hook_harness_allows_ordinary_writes():
    """无运行时钩子时，harness-check 不假装拦截普通写——终态门才是控制点。"""
    assert HARNESS_PROFILES["codex"]["interception"].startswith("none")
    d = check_tool_call(
        {"tool_name": "Write", "tool_input": {"file_path": "src/generated.py"}}
    )
    assert d.permissionDecision == "allow"
    assert "观察" in d.reason or "不在受控" in d.reason


def test_scenario12_terminal_gate_still_blocks(tmp_path):
    """终态门：fail 规则存活时 gate 阻断（wrap/CI/pre-push 共用同一入口）。"""
    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/ci-deploy", work)
    # RELEASE-001 有 legacy_publish → fail
    assert main(["gate", str(work)]) == 1

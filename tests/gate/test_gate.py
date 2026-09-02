"""B1 终点执行器测试：gate 三态、hook 安装边界、self-test 演习。"""
from pathlib import Path

from sopcontrol.cli import HOOK_MARKER, main

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "corpus" / "fixtures"


def test_gate_blocks_on_fail_verdict():
    # jobflow 与 ci-deploy 均存在 legacy 绕过（fail 判定）→ 阻断
    assert main(["gate", str(FIXTURES / "jobflow-preview")]) == 1
    assert main(["gate", str(FIXTURES / "ci-deploy")]) == 1


def test_gate_warns_but_passes_on_gap_only():
    # shop-checkout 只有 gap（未接线/未测试），没有 fail → 放行（L2/L3 阶梯）
    assert main(["gate", str(FIXTURES / "shop-checkout")]) == 0


def test_gate_fail_closed_on_uninitialized_project(tmp_path, capsys):
    # 门无法审计时必须阻断（fail-closed），并给出可行动的修复指引
    assert main(["gate", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "fail-closed" in err and "sopctl init" in err


def test_gate_does_not_miss_legacy_entry_after_500_code_files(tmp_path, capsys):
    """大型仓库也必须扫描完整；旧入口不能因遍历上限而从门禁视野消失。"""
    work = tmp_path / "large-project"
    work.mkdir()
    assert main(["init", str(work)]) == 0

    docs = work / "docs"
    docs.mkdir()
    (docs / "sop.md").write_text("发货必须经过 safe_entry。\n", encoding="utf-8")

    app = work / "app"
    app.mkdir()
    (app / "a000_consumer.py").write_text(
        "def safe_entry(package):\n    return package\n",
        encoding="utf-8",
    )
    (app / "a001_consumer_test.py").write_text(
        "from a000_consumer import safe_entry\n",
        encoding="utf-8",
    )
    for index in range(498):
        (app / f"100_filler_{index:03d}.py").write_text(
            f"VALUE_{index} = {index}\n",
            encoding="utf-8",
        )
    (app / "zzz_legacy.py").write_text(
        "def legacy_entry(package):\n    return package\n",
        encoding="utf-8",
    )

    assert main([
        "rule", "add", str(work),
        "--id", "SCAN-001",
        "--statement", "发货必须经过 safe_entry",
        "--status", "accepted",
        "--source-ref", "docs/sop.md",
        "--consumer-marker", "safe_entry",
        "--legacy-marker", "legacy_entry",
    ]) == 0

    assert main(["gate", str(work)]) == 1
    assert "旧入口 [legacy_entry]" in capsys.readouterr().err


def test_hook_install_idempotent_and_refuses_foreign_hooks(tmp_path):
    git_hooks = tmp_path / ".git" / "hooks"
    git_hooks.mkdir(parents=True)
    hook_path = git_hooks / "pre-push"

    assert main(["hook", "install", str(tmp_path)]) == 0
    content = hook_path.read_text()
    assert HOOK_MARKER in content and "sopctl gate" in content
    assert hook_path.stat().st_mode & 0o111  # 可执行

    assert main(["hook", "install", str(tmp_path)]) == 0  # 幂等重装

    hook_path.write_text("#!/bin/sh\necho custom\n")
    assert main(["hook", "install", str(tmp_path)]) == 2  # 拒绝覆盖他人钩子
    assert "custom" in hook_path.read_text()  # 原内容未被破坏


def test_self_test_drills_pass(capsys):
    assert main(["self-test"]) == 0
    out = capsys.readouterr().out
    assert "旧入口存活被阻断" in out
    assert "清洁现场被放行" in out
    assert "账本篡改被阻断" in out

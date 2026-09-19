"""WP-A2：残缺布局受控修复 + CLI 位置参数回归（项目既定语法不动）。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from sopcontrol.cli import main
from sopcontrol.registry import Registry


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True, timeout=30)


def test_init_repairs_partial_layout_preserving_rules(tmp_path, capsys):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    # 模拟残缺：删掉 evidence/ 与 manifest，保留 rules/registry
    import shutil

    shutil.rmtree(work / ".sopcontrol" / "evidence")
    (work / ".sopcontrol" / "manifest.yaml").unlink()
    assert main(["init", str(work)]) == 0
    out = capsys.readouterr().out
    assert "布局已修复" in out
    assert (work / ".sopcontrol" / "evidence").is_dir()
    assert (work / ".sopcontrol" / "manifest.yaml").is_file()
    assert (work / ".sopcontrol" / "rules" / "registry.yaml").is_file()


def test_init_refuses_corrupt_registry_without_faking(tmp_path, capsys):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    (work / ".sopcontrol" / "rules" / "registry.yaml").write_text(
        "rules: [unclosed\n", encoding="utf-8")
    assert main(["init", str(work)]) == 2
    err = capsys.readouterr().err
    assert "损坏" in err and "未改动" in err
    # 未被悄悄清空为看似正常的空文件
    assert "unclosed" in (work / ".sopcontrol" / "rules" / "registry.yaml").read_text(
        encoding="utf-8")


def test_init_complete_layout_skips_cleanly(tmp_path, capsys):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    assert main(["init", str(work)]) == 0
    assert "已初始化，跳过" in capsys.readouterr().out


def test_cli_positional_paths_stable(tmp_path, capsys, monkeypatch):
    """项目既定语法回归：logic plan <file> [--flags] [path]；task rebind <id> --model [path]。"""
    work = tmp_path / "p"
    work.mkdir()
    _git_init(work)
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    # logic plan 位置参数：file 在前，path 在后
    plan = work / "plan.yaml"
    plan.write_text("plan_id: x\n", encoding="utf-8")
    monkeypatch.chdir(work)
    rc = main(["logic", "plan", str(plan), "--freeze", str(work)])
    out = capsys.readouterr()
    assert rc != 2 or "unrecognized arguments" not in (out.out + out.err)
    # task rebind 位置参数：task_id 在前，path 在后（解析层回归，不跑完整门）
    import argparse

    from sopcontrol.cli import build_parser

    ns = build_parser().parse_args(
        ["task", "rebind", "TASK-0001", "--model", "m", str(work)])
    assert ns.task_id == "TASK-0001" and ns.model == "m" and ns.path == str(work)
    ns2 = build_parser().parse_args(
        ["logic", "plan", str(plan), "--freeze", str(work)])
    assert ns2.file == str(plan) and ns2.path == str(work) and ns2.freeze is True


def test_init_permission_denied_fails_cleanly(tmp_path, capsys):
    """A2：无写权限时干净失败（无 traceback、无半截布局）。"""
    import traceback as _tb

    work = tmp_path / "p"
    work.mkdir()
    work.chmod(0o555)
    try:
        rc = main(["init", str(work)])
    finally:
        work.chmod(0o755)
    assert rc != 0
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "写权限" in err
    assert not (work / ".sopcontrol").exists()

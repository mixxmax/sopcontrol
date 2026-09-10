"""P2 切片 D：Windows hook 安装矩阵（mock 平台；达尔文机无 Windows 活环境）。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from sopcontrol.attachment import apply_attachment, plan_attachment
from sopcontrol.cli import main
from sopcontrol.product import compat_check
from sopcontrol.resolve_cli import hook_shell_available


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True, timeout=30)


def _hook_path(root: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-path", "hooks/pre-push"],
        capture_output=True, text=True, timeout=15, check=True,
    )
    path = Path(proc.stdout.strip())
    return path if path.is_absolute() else (root / path)


def test_shell_matrix_posix_and_windows():
    ok, _ = hook_shell_available(os_name="posix")
    assert ok is True
    ok, _ = hook_shell_available(os_name="nt", find_bash=lambda prog: r"C:\Git\bin\bash.exe")
    assert ok is True
    ok, why = hook_shell_available(os_name="nt", find_bash=lambda prog: None)
    assert ok is False and "bash" in why and "重跑" in why


def test_windows_without_shell_defers_hook_without_writing(tmp_path, monkeypatch):
    import sopcontrol.resolve_cli as rc

    monkeypatch.setattr(rc, "hook_shell_available", lambda **kw: (False, "无 bash（测试桩）"))
    work = tmp_path / "g"
    work.mkdir()
    _git_init(work)

    plan = plan_attachment(work)
    assert "git_hooks" in plan.deferred_surfaces
    assert not [c for c in plan.safe_changes if c.change_id == "hook_pre_push"]
    report = apply_attachment(plan)
    assert not _hook_path(work).exists()


def test_windows_with_shell_installs_normally(tmp_path, monkeypatch):
    import sopcontrol.resolve_cli as rc

    monkeypatch.setattr(rc, "hook_shell_available", lambda **kw: (True, "windows-bash（测试桩）"))
    work = tmp_path / "g"
    work.mkdir()
    _git_init(work)

    plan = plan_attachment(work)
    hook_change = next(c for c in plan.safe_changes if c.change_id == "hook_pre_push")
    assert hook_change.strategy == "isolate"
    apply_attachment(plan)
    assert _hook_path(work).exists()


def test_hook_install_refuses_without_shell(tmp_path, monkeypatch, capsys):
    import sopcontrol.resolve_cli as rc

    monkeypatch.setattr(rc, "hook_shell_available", lambda **kw: (False, "无 bash（测试桩）"))
    work = tmp_path / "g"
    work.mkdir()
    _git_init(work)

    assert main(["hook", "install", str(work)]) == 2
    assert "拒绝安装" in capsys.readouterr().err
    assert not _hook_path(work).exists()


def test_compat_reports_hook_shell(tmp_path, monkeypatch):
    import sopcontrol.resolve_cli as rc

    report = compat_check()
    assert report["hook_shell"]["available"] is True
    monkeypatch.setattr(rc, "hook_shell_available", lambda **kw: (False, "无 bash（测试桩）"))
    report = compat_check()
    assert report["hook_shell"]["available"] is False
    assert any("hook shell" in i for i in report["issues"])
    assert report["ok"] is False

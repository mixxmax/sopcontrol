"""REL-004：pre-push hook resolver 三场景验收。

场景：fresh install 写入 resolver 链；升级时只刷新 sopctl 自有钩子、保留
第三方钩子；GUI/无 PATH 环境经 .venv 或 SOPCTL_BIN 解析，全部失败时
fail-closed 并给出可执行修复命令（且明确禁止 --no-verify）。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from sopcontrol.cli import main
from sopcontrol.resolve_cli import hook_script_body


def _git_init(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, timeout=30)
    hook = path / ".git" / "hooks"
    hook.mkdir(parents=True, exist_ok=True)


def _install(path: Path) -> int:
    return main(["hook", "install", str(path)])


def _hook_text(path: Path) -> str:
    return (path / ".git" / "hooks" / "pre-push").read_text(encoding="utf-8")


def _run_hook(path: Path, *, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin",  # 刻意不含 sopctl，也不含 venv
        "HOME": str(path / "home"),
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["sh", str(path / ".git" / "hooks" / "pre-push")],
        cwd=str(path),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_fresh_install_writes_resolver_chain(tmp_path):
    _git_init(tmp_path)

    rc = _install(tmp_path)

    assert rc == 0
    body = _hook_text(tmp_path)
    assert "# sopcontrol-hook v1" in body
    assert "SOPCTL_BIN" in body
    assert ".venv/bin/sopctl" in body
    assert "sopcontrol.cli" in body
    assert "--no-verify" not in body.replace("Do not use --no-verify.", "")


def test_upgrade_refreshes_own_hook_and_preserves_third_party(tmp_path):
    _git_init(tmp_path)
    hooks = tmp_path / ".git" / "hooks"
    old_own = "#!/bin/sh\n# sopcontrol-hook v1\nexec sopctl gate .\n"
    (hooks / "pre-push").write_text(old_own, encoding="utf-8")

    assert _install(tmp_path) == 0
    body = _hook_text(tmp_path)
    assert "SOPCTL_BIN" in body          # 已刷新为 resolver 版
    assert "exec sopctl gate ." not in body

    # 第三方钩子（无 sopctl 标记）必须拒绝覆盖且原样保留
    foreign = "#!/bin/sh\necho my-own-hook\n"
    (hooks / "pre-push").write_text(foreign, encoding="utf-8")
    assert _install(tmp_path) == 2
    assert _hook_text(tmp_path) == foreign


def test_gui_no_path_resolves_project_venv_stub(tmp_path):
    _git_init(tmp_path)
    assert _install(tmp_path) == 0
    # 伪造项目 venv：sopctl stub 记录调用参数后成功退出
    stub_dir = tmp_path / ".venv" / "bin"
    stub_dir.mkdir(parents=True, exist_ok=True)
    log = tmp_path / "stub.log"
    stub = stub_dir / "sopctl"
    stub.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexit 0\n', encoding="utf-8")
    stub.chmod(0o755)

    proc = _run_hook(tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert log.read_text(encoding="utf-8").startswith("gate")


def test_gui_no_path_resolves_sopctl_bin_override(tmp_path):
    _git_init(tmp_path)
    assert _install(tmp_path) == 0
    log = tmp_path / "bin-stub.log"
    stub_dir = tmp_path / "bin-stub"
    stub_dir.mkdir(exist_ok=True)
    stub = stub_dir / "sopctl"
    stub.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexit 0\n', encoding="utf-8")
    stub.chmod(0o755)

    proc = _run_hook(tmp_path, extra_env={"SOPCTL_BIN": str(stub)})

    assert proc.returncode == 0, proc.stderr
    assert log.read_text(encoding="utf-8").startswith("gate")


def test_gui_no_path_fail_closed_with_fix_command(tmp_path):
    _git_init(tmp_path)
    assert _install(tmp_path) == 0
    # 无 .venv、无 SOPCTL_BIN、PATH 无 sopctl；python3 回退在无安装目录必然失败

    proc = _run_hook(tmp_path)

    assert proc.returncode != 0
    assert "fail-closed" in proc.stderr
    assert "SOPCTL_BIN=" in proc.stderr
    assert "Do not use --no-verify." in proc.stderr

"""Phase A: second attach is semantically a no-op."""
from __future__ import annotations

import subprocess
from pathlib import Path

from sopcontrol.cli import main


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True, timeout=30)


def test_second_attach_zero_semantic_change(tmp_path):
    work = tmp_path / "g"
    work.mkdir()
    _git_init(work)
    assert main(["attach", str(work)]) == 0
    agents1 = (work / "AGENTS.md").read_text(encoding="utf-8") if (work / "AGENTS.md").exists() else ""
    hook = None
    # find hook via git-path
    proc = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "--git-path", "hooks/pre-push"],
        capture_output=True, text=True, timeout=15, check=True,
    )
    hook_path = Path(proc.stdout.strip())
    if not hook_path.is_absolute():
        hook_path = work / hook_path
    hook1 = hook_path.read_text(encoding="utf-8") if hook_path.exists() else ""

    assert main(["attach", str(work)]) == 0
    agents2 = (work / "AGENTS.md").read_text(encoding="utf-8") if (work / "AGENTS.md").exists() else ""
    hook2 = hook_path.read_text(encoding="utf-8") if hook_path.exists() else ""
    assert agents1 == agents2
    assert hook1 == hook2

"""Phase A: existing pre-push is chained, not overwritten."""
from __future__ import annotations

import subprocess
from pathlib import Path

from sopcontrol.attachment import CHAIN_MARKER, apply_attachment, plan_attachment
from sopcontrol.cli import main


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


def test_existing_foreign_hook_is_chained(tmp_path):
    work = tmp_path / "g"
    work.mkdir()
    _git_init(work)
    hook = _hook_path(work)
    hook.parent.mkdir(parents=True, exist_ok=True)
    original = "#!/bin/sh\necho foreign-hook-ran\nexit 0\n"
    hook.write_text(original, encoding="utf-8")
    hook.chmod(0o755)

    plan = plan_attachment(work)
    hook_change = next(c for c in plan.safe_changes if c.change_id == "hook_pre_push")
    assert hook_change.strategy == "chain"
    report = apply_attachment(plan)
    assert report.connection_state in {"connected", "connected_with_gaps"}

    text = hook.read_text(encoding="utf-8")
    assert CHAIN_MARKER in text
    assert "sopcontrol" in text.lower() or "sopctl" in text or "sopcontrol.cli" in text
    # backup exists and preserves original
    backups = list((work / ".sopcontrol-local" / "attachment" / "backups").glob("pre-push.*.orig"))
    assert backups
    assert "foreign-hook-ran" in backups[0].read_text(encoding="utf-8")


def test_git_path_used_not_only_dot_git_hooks(tmp_path):
    """Hook install must use git rev-parse --git-path (worktree-safe)."""
    work = tmp_path / "g"
    work.mkdir()
    _git_init(work)
    assert main(["attach", str(work)]) == 0
    hook = _hook_path(work)
    assert hook.exists()
    assert "sopcontrol" in hook.read_text(encoding="utf-8").lower() or "sopctl" in hook.read_text(
        encoding="utf-8"
    )

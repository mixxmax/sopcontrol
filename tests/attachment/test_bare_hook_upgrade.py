"""P1: upgrade path for old bare pre-push hooks (HOOK_MARKER, no resolver)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from sopcontrol.attachment import (
    RESOLVER_SIGNATURE,
    apply_attachment,
    plan_attachment,
)

# 真实实例：本仓库自带裸 hook（直接 exec sopctl，无 resolver）。
BARE_HOOK = """#!/bin/sh
# sopcontrol-hook v1
# 终态门：fail 判定或账本篡改则阻断 push（gap 仅警告）
exec sopctl gate "$(git rev-parse --show-toplevel)"
"""


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


def _work_with_bare_hook(tmp_path: Path) -> tuple[Path, Path]:
    work = tmp_path / "g"
    work.mkdir()
    _git_init(work)
    hook = _hook_path(work)
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(BARE_HOOK, encoding="utf-8")
    hook.chmod(0o755)
    return work, hook


def test_bare_hook_plans_upgrade_not_noop(tmp_path):
    work, _ = _work_with_bare_hook(tmp_path)
    plan = plan_attachment(work)
    hook_change = next(c for c in plan.safe_changes if c.change_id == "hook_pre_push")
    assert hook_change.strategy == "upgrade"


def test_bare_hook_upgraded_to_resolver_with_backup(tmp_path):
    work, hook = _work_with_bare_hook(tmp_path)
    report = apply_attachment(plan_attachment(work))
    assert report.connection_state in {"connected", "connected_with_gaps"}

    text = hook.read_text(encoding="utf-8")
    assert RESOLVER_SIGNATURE in text
    assert "SOPCTL_BIN" in text
    assert hook.stat().st_mode & 0o111

    backups = list((work / ".sopcontrol-local" / "attachment" / "backups").glob("pre-push.*.bare"))
    assert backups
    assert backups[0].read_text(encoding="utf-8") == BARE_HOOK


def test_upgraded_hook_is_idempotent(tmp_path):
    work, hook = _work_with_bare_hook(tmp_path)
    apply_attachment(plan_attachment(work))

    plan2 = plan_attachment(work)
    hook_change = next(c for c in plan2.safe_changes if c.change_id == "hook_pre_push")
    assert hook_change.strategy == "noop"
    before = hook.read_text(encoding="utf-8")
    apply_attachment(plan2)
    assert hook.read_text(encoding="utf-8") == before


def test_bare_hook_status_and_verify_do_not_crash(tmp_path):
    """0087 回归：bare 状态必须进 AttachmentStatus 字面量；verify 全链路可跑。"""
    from sopcontrol.attach_verify import verify_attachment
    from sopcontrol.attachment import attachment_status
    from sopcontrol.coverage_probe import verify_surface

    work, _ = _work_with_bare_hook(tmp_path)
    status = attachment_status(work)
    assert status.git_hook == "bare"

    report = verify_attachment(work)
    assert report["schema_version"] == "1"
    for item in report["surfaces"]:
        assert set(item) == {
            "surface", "state", "why", "safe_next_action", "user_input_required",
        }

    git_probe = verify_surface(work, "git_hooks")
    assert git_probe.passed is False  # bare 不是已验证的强制钩：fail-closed

"""Phase A: one adapter conflict must not abort the whole attach."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sopcontrol.attachment import apply_attachment, plan_attachment


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True, timeout=30)


def test_corrupt_claude_settings_defers_only_claude(tmp_path):
    work = tmp_path / "g"
    work.mkdir()
    _git_init(work)
    settings = work / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{not-json", encoding="utf-8")

    plan = plan_attachment(work)
    assert any(c.kind == "claude_settings_corrupt" for c in plan.conflicts)
    report = apply_attachment(plan)
    assert report.connection_state in {"connected", "connected_with_gaps"}
    assert (work / ".sopcontrol").exists()
    # Claude deferred, but identity/hook still done
    assert any(a.change_id == "identity" and a.outcome == "applied" for a in report.applied)


def test_foreign_opencode_plugin_uses_isolate(tmp_path):
    work = tmp_path / "g"
    work.mkdir()
    _git_init(work)
    plugin = work / ".opencode" / "plugins" / "sopcontrol.js"
    plugin.parent.mkdir(parents=True)
    plugin.write_text("// someone else's plugin\nexport const X = 1\n", encoding="utf-8")

    plan = plan_attachment(work)
    oc = next(c for c in plan.safe_changes if c.change_id == "hook_opencode")
    assert oc.strategy == "isolate"
    assert oc.path.endswith("sopcontrol-attach.js")
    report = apply_attachment(plan)
    assert report.connection_state in {"connected", "connected_with_gaps"}
    assert plugin.read_text(encoding="utf-8").startswith("// someone else")
    alt = work / ".opencode" / "plugins" / "sopcontrol-attach.js"
    assert alt.exists()
    assert "sopcontrol.cli" in alt.read_text(encoding="utf-8")

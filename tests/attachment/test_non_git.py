"""Phase A: non-git projects still get identity and control dir."""
from __future__ import annotations

from pathlib import Path

from sopcontrol.attachment import attachment_status
from sopcontrol.cli import main


def test_non_git_attach_connects_without_hooks(tmp_path):
    work = tmp_path / "bare"
    work.mkdir()
    (work / "app.py").write_text("print(1)\n", encoding="utf-8")
    assert main(["attach", str(work)]) == 0
    status = attachment_status(work)
    assert status.connected is True
    assert status.git_hook == "unavailable"
    assert "git_unavailable" in status.gaps or "git_hooks" in " ".join(status.gaps)
    assert (work / ".sopcontrol" / "identity.yaml").exists()

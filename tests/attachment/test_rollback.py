"""Phase A: apply writes a rollback receipt under .sopcontrol-local/."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sopcontrol.attachment import plan_detachment
from sopcontrol.cli import main


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True, timeout=30)


def test_receipt_lists_applied_changes(tmp_path):
    work = tmp_path / "g"
    work.mkdir()
    _git_init(work)
    assert main(["attach", str(work), "--json"]) == 0
    receipts = list((work / ".sopcontrol-local" / "attachment" / "receipts").glob("attach-*.json"))
    assert receipts
    data = json.loads(receipts[-1].read_text(encoding="utf-8"))
    assert data["schema_version"] == "1"
    assert data["applied"]
    assert data["connection_state"] in {"connected", "connected_with_gaps"}


def test_detach_plan_preview_only(tmp_path, capsys):
    work = tmp_path / "g"
    work.mkdir()
    _git_init(work)
    assert main(["attach", str(work)]) == 0
    assert main(["detach", str(work)]) == 2  # requires --plan
    assert main(["detach", str(work), "--plan"]) == 0
    out = capsys.readouterr().out
    assert "Detach preview" in out or "removable" in out
    preview = plan_detachment(work)
    assert preview.removable
    assert any("registry" in k for k in preview.keep)

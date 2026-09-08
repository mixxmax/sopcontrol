"""Phase A: attach --plan is read-only discovery."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sopcontrol.attachment import plan_attachment
from sopcontrol.cli import main


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True, timeout=30)


def test_plan_greenfield_is_readonly(tmp_path):
    work = tmp_path / "g"
    work.mkdir()
    _git_init(work)
    (work / "README.md").write_text("x\n", encoding="utf-8")
    before = {p.relative_to(work) for p in work.rglob("*") if p.is_file()}

    plan = plan_attachment(work)
    assert plan.lifecycle == "greenfield"
    assert any(c.change_id == "init" for c in plan.safe_changes)
    after = {p.relative_to(work) for p in work.rglob("*") if p.is_file()}
    assert before == after


def test_plan_cli_json(tmp_path, capsys):
    work = tmp_path / "g"
    work.mkdir()
    assert main(["attach", str(work), "--plan", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == "1"
    assert data["lifecycle"] == "greenfield"
    assert not (work / ".sopcontrol").exists()

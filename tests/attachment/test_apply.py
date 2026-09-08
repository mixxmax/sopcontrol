"""Phase A: attach apply reaches Connected without business source edits."""
from __future__ import annotations

import subprocess
from pathlib import Path

from sopcontrol.attachment import apply_attachment, attachment_status, plan_attachment
from sopcontrol.cli import main


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True, timeout=30)


def test_attach_greenfield_connects(tmp_path):
    work = tmp_path / "g"
    work.mkdir()
    _git_init(work)
    (work / "src").mkdir()
    (work / "src" / "app.py").write_text("x=1\n", encoding="utf-8")
    src_before = (work / "src" / "app.py").read_text(encoding="utf-8")

    assert main(["attach", str(work)]) == 0
    assert (work / ".sopcontrol" / "rules" / "registry.yaml").exists()
    assert (work / ".sopcontrol" / "identity.yaml").exists()
    status = attachment_status(work)
    assert status.connected is True
    assert status.project_id.startswith("proj-")
    assert (work / "src" / "app.py").read_text(encoding="utf-8") == src_before
    # no accepted rules auto-added
    reg = (work / ".sopcontrol" / "rules" / "registry.yaml").read_text(encoding="utf-8")
    assert "rules: []" in reg or reg.strip() == "rules: []"


def test_attach_existing_fixture(tmp_path):
    root = Path(__file__).resolve().parents[2]
    src = root / "corpus" / "fixtures" / "shop-checkout"
    work = tmp_path / "shop"
    import shutil

    shutil.copytree(src, work)
    _git_init(work)
    subprocess.run(["git", "add", "-A"], cwd=work, check=True, timeout=60)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=work, check=True, timeout=60)

    plan = plan_attachment(work)
    assert plan.lifecycle in {"existing", "mature"}
    report = apply_attachment(plan)
    assert report.connection_state in {"connected", "connected_with_gaps"}
    assert report.business_source_edits == 0
    assert report.model_calls == 0
    assert Path(report.rollback_receipt_path).exists()

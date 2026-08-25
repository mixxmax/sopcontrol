"""投影漂移检测。"""
import shutil

from sopcontrol.cli import main


def test_project_check_detects_stale(tmp_path):
    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/ci-deploy", work)
    assert main(["project", "all", str(work)]) == 0
    assert main(["project", "check", str(work)]) == 0

    agents = work / "AGENTS.md"
    text = agents.read_text(encoding="utf-8")
    agents.write_text(text.replace("DEPLOY-001", "DEPLOY-001-TAMPERED"), encoding="utf-8")
    assert main(["project", "check", str(work)]) == 1

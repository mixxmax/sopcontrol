"""Phase D: sopctl enter — supervised/cooperative/testing runtimes."""
from __future__ import annotations

import json
import os
from pathlib import Path

from sopcontrol.cli import main
from sopcontrol.coverage import control_coverage
from sopcontrol.runtime import ENV_PROJECT_ID, ENV_ROOT, ENV_RUN_ID, enter, get_runtime, identity_env
from sopcontrol.runtime_model import RuntimePolicy


def test_testing_provider_receipt_and_identity(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    session = enter(work, ["echo", "hi"], mode="testing")
    receipt = session.wait()
    assert receipt.exit_code == 0
    assert receipt.run_id.startswith("run-")
    assert receipt.project_id.startswith("proj-")
    assert receipt.worktree_id
    assert len(receipt.process_events) >= 2
    assert receipt.business_tree_damaged is False
    assert "file_enforce_unsupported" in receipt.gaps
    assert "network_enforce_unsupported" in receipt.gaps
    assert receipt.capabilities.unbypassable is False
    path = Path(receipt.detail["receipt_path"])
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1"
    assert ENV_ROOT in data["detail"]["identity_env_keys"]
    assert ENV_RUN_ID in data["detail"]["identity_env_keys"]


def test_supervised_runs_real_command_and_emits_process_events(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    (work / "marker.txt").write_text("keep\n", encoding="utf-8")
    assert main(["init", str(work)]) == 0
    # Child process via shell so ps can see a descendant on some platforms;
    # at minimum main spawn+exit are recorded.
    session = enter(
        work,
        ["python3", "-c", "import os,time; print(os.environ.get('SOPCONTROL_RUN_ID','')); time.sleep(0.3)"],
        mode="supervised",
        policy=RuntimePolicy(mode="supervised", timeout_seconds=30),
    )
    receipt = session.wait()
    assert receipt.exit_code == 0
    kinds = {e.kind for e in receipt.process_events}
    assert "spawn" in kinds
    assert "exit" in kinds
    assert receipt.capabilities.process_events is True
    assert receipt.capabilities.file_enforce is False
    assert (work / "marker.txt").read_text(encoding="utf-8") == "keep\n"
    assert receipt.business_tree_damaged is False


def test_enter_cli_testing_json(tmp_path, capsys):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    rc = main([
        "enter", "--path", str(work), "--mode", "testing", "--json", "--", "true",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    # skip banner lines
    blob = out[out.find("{") :]
    data = json.loads(blob)
    assert data["mode"] == "supervised" or data["capabilities"]["mode"] == "supervised"
    assert data["gaps"]
    assert data["capabilities"]["unbypassable"] is False


def test_request_file_enforce_is_gap_not_verified(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    session = enter(
        work,
        ["true"],
        mode="testing",
        policy=RuntimePolicy(mode="supervised", request_file_enforce=True),
    )
    receipt = session.wait()
    assert "requested_file_enforce_unsupported" in receipt.gaps
    assert receipt.capabilities.file_enforce is False


def test_coverage_marks_runtime_supervised_honestly(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    report = control_coverage(work)
    rt = next(s for s in report.surfaces if s.surface == "runtime_supervised")
    assert rt.state in {"observable", "gap", "detected"}
    assert rt.state != "verified"
    assert "unsupported" in (rt.gap_reason or "") or "not_unbypassable" in (rt.gap_reason or "")


def test_identity_env_inherited_keys():
    env = identity_env(Path("."), run_id="run-x", mode="supervised")
    assert env[ENV_RUN_ID] == "run-x"
    assert ENV_PROJECT_ID in env
    assert ENV_ROOT in env


def test_providers_registered():
    assert get_runtime("supervised").name == "supervised"
    assert get_runtime("cooperative").name == "cooperative"
    assert get_runtime("testing").name == "testing"

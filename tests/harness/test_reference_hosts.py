"""WP-K：双参考宿主缝验证（明确标注：非 JobsFlow 证据）。

覆盖：bridge admission（只读/受控写/hook/高影响票据）、OperatorContract
昂贵判定、输入输出集合、集合缩小、业务 stub、失败重试。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from sopcontrol.cli import main

HOST_CLI = Path("examples/host-cli/host_cli.py")
HOST_WORKER = Path("examples/host-worker/host_worker.py")


@pytest.fixture()
def project(tmp_path):
    assert main(["init", str(tmp_path)]) == 0
    return tmp_path


def _cli(project, *argv):
    proc = subprocess.run(
        [sys.executable, str(HOST_CLI), "--project", str(project), *argv],
        capture_output=True, text=True, timeout=60, cwd=".",
        env={"PYTHONPATH": ".", "PATH": "/usr/bin:/bin"},
    )
    return proc


def test_host_cli_read_and_status(project, tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello-host\n", encoding="utf-8")
    r = _cli(project, "read", str(f))
    assert r.returncode == 0 and "hello-host" in r.stdout
    r = _cli(project, "status")
    assert r.returncode == 0 and json.loads(r.stdout)["executed"] is True


def test_host_cli_controlled_write(project, tmp_path):
    target = tmp_path / "out" / "note.txt"
    r = _cli(project, "write", str(target), "受控写")
    assert r.returncode == 0
    assert target.read_text(encoding="utf-8") == "受控写"
    assert json.loads(r.stdout)["bridge_ok"] is True


def test_host_cli_hook_admits_and_refuses(project):
    ok = subprocess.run(
        [sys.executable, str(HOST_CLI), "--project", str(project), "hook"],
        input=json.dumps({"argv": ["true"], "action": "status"}),
        capture_output=True, text=True, timeout=60, cwd=".",
        env={"PYTHONPATH": ".", "PATH": "/usr/bin:/bin"},
    )
    assert ok.returncode == 0
    bad = subprocess.run(
        [sys.executable, str(HOST_CLI), "--project", str(project), "hook"],
        input=json.dumps({"argv": ["true"], "action": "noop"}),
        capture_output=True, text=True, timeout=60, cwd=".",
        env={"PYTHONPATH": ".", "PATH": "/usr/bin:/bin"},
    )
    assert bad.returncode == 1


def test_host_cli_high_impact_ticket(project):
    r = _cli(project, "fetch")
    assert r.returncode == 0 and json.loads(r.stdout)["fetched"] is True


def test_host_worker_sets_narrow_business_retry():
    import importlib.util
    spec = importlib.util.spec_from_file_location("host_worker", str(HOST_WORKER))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    batch = mod.run_batch([{"id": "a", "text": "xyz"}, {"id": "b", "text": ""}])
    assert [o["id"] for o in batch["outputs"]] == ["a", "b"]
    desc = mod.expensive_op_descriptor()
    assert desc["is_expensive"] is True and desc["needs_admission"] is True
    narrowed = mod.narrow(batch["outputs"], lambda o: o["score"] > 0)
    assert [o["id"] for o in narrowed] == ["a"]
    assert mod.business_check([{"id": "z", "score": -1}])[0]["severity"] == "blocking"
    assert mod.business_check([{"id": "z", "score": 1}]) == []
    assert mod.run_with_retry("abcd")["attempts"] == 2

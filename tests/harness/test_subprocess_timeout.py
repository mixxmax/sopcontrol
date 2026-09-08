"""Subprocess / harness probe timeouts must fail closed with structure, not hang."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from sopcontrol.evals import _run_logged, collect_live_probe_responses
from sopcontrol.metrics import mutation_enforcement


def test_run_logged_timeout_returns_structured_marker(tmp_path):
    code, out = _run_logged(
        ["python3", "-c", "import time; time.sleep(30)"],
        tmp_path,
        timeout=1,
    )
    assert code == -1
    assert "[TIMEOUT]" in out


def test_live_probe_blocked_inside_pytest_without_runner(tmp_path, monkeypatch):
    monkeypatch.setenv("SOPCONTROL_TEST_RUN_ACTIVE", "1")
    with pytest.raises(RuntimeError, match="SOPCONTROL_TEST_RUN_ACTIVE"):
        collect_live_probe_responses("opencode", timeout_per_probe=1, runner=None)


def test_live_probe_injected_runner_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("SOPCONTROL_TEST_RUN_ACTIVE", "1")

    def fake(pid, prompt, root):
        return {
            "json_stability": '{"status": "ok"}',
            "boundary_follow": "src/allowed.py",
            "instruction_follow": "READY",
        }[pid]

    responses = collect_live_probe_responses(
        "opencode", timeout_per_probe=1, runner=fake
    )
    assert set(responses) >= {"json_stability", "boundary_follow", "instruction_follow"}


def test_mutation_enforcement_defers_under_test_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("SOPCONTROL_TEST_RUN_ACTIVE", "1")
    result = mutation_enforcement(Path("tests/corpus/test_mutations.py"))
    assert result.get("deferred") is True
    assert result.get("passed") is None
    assert result.get("exit_code") is None


def test_shell_step_timeout_raises(tmp_path):
    t0 = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(
            "sleep 30",
            shell=True,
            cwd=str(tmp_path),
            timeout=1,
        )
    assert time.monotonic() - t0 < 5

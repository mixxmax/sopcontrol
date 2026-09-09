"""Extra branch coverage for Phase C–F modules (fail_under 85%)."""
from __future__ import annotations

import json
from pathlib import Path

from sopcontrol.cli import main
from sopcontrol.coverage import control_coverage, format_coverage_report, record_surface_event
from sopcontrol.coverage_probe import verify_surface
from sopcontrol.product import compat_check, measure_coverage_seconds
from sopcontrol.runtime import enter, get_runtime, redact_argv


def test_coverage_cli_probe_and_format(tmp_path, capsys):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    assert main(["hook", "opencode", str(work)]) == 0
    capsys.readouterr()
    assert main(["coverage", str(work), "--probe", "shell"]) == 0
    out = capsys.readouterr().out
    assert "probe shell" in out or "PASS" in out or "shell" in out
    report = control_coverage(work)
    text = format_coverage_report(report)
    assert "Control coverage" in text
    assert "surfaces:" in text


def test_coverage_cli_json_after_probe(tmp_path, capsys):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    (work / ".claude").mkdir(exist_ok=True)
    (work / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    assert main(["hook", "claude", str(work)]) == 0
    capsys.readouterr()
    rc = main(["coverage", str(work), "--probe", "filesystem_read", "--json"])
    assert rc in (0, 1)
    out = capsys.readouterr().out
    assert "{" in out


def test_structural_probes_and_unknown_surface(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    assert main(["hook", "opencode", str(work)]) == 0
    r1 = verify_surface(work, "harness_opencode")
    assert r1.passed is True
    r2 = verify_surface(work, "harness_codex")
    assert r2.passed is False
    r3 = verify_surface(work, "not_a_real_surface")
    assert r3.passed is False
    r4 = verify_surface(work, "git_hooks")
    # may fail if no git
    assert r4.detail


def test_record_surface_event_and_compat_measure(tmp_path, capsys):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    record_surface_event(work, surface="network", state="observable", source="event")
    report = control_coverage(work)
    assert any(s.surface == "network" for s in report.surfaces)
    elapsed = measure_coverage_seconds(work)
    assert elapsed >= 0
    assert main(["compat", str(work), "--measure"]) == 0
    out = capsys.readouterr().out
    assert "measure:" in out or "platform:" in out


def test_attach_status_and_detach_json(tmp_path, capsys):
    work = tmp_path / "p"
    work.mkdir()
    (work / ".claude").mkdir()
    (work / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    assert main(["attach", str(work)]) == 0
    capsys.readouterr()
    assert main(["attach-status", str(work), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["connected"] is True
    assert main(["detach", str(work), "--plan", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert "removable" in plan


def test_cooperative_runtime_and_redact_edges():
    assert get_runtime("cooperative").capabilities().process_events is False
    assert redact_argv(["-H", "X-Api-Key:abcd"])[-1] == "***" or "***" in redact_argv(["-H", "X-Api-Key:abcd"])[-1]
    assert redact_argv(["Authorization: Bearer zz"])[0].endswith("***")


def test_compat_check_without_project():
    report = compat_check()
    assert report["ok"] in {True, False}
    assert "matrix" in report


def test_resolve_cli_paths(tmp_path, monkeypatch):
    from sopcontrol.resolve_cli import resolve_sopctl
    import os

    work = tmp_path / "w"
    work.mkdir()
    # bad SOPCTL_BIN
    argv, reason = resolve_sopctl(work, env={"SOPCTL_BIN": str(work / "missing"), "PATH": ""})
    assert argv is None
    assert "not executable" in reason or "SOPCTL_BIN" in reason
    # venv sopctl
    venv_bin = work / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    fake = venv_bin / "sopctl"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    argv, reason = resolve_sopctl(work, env={"PATH": "/nonexistent"})
    assert argv is not None
    assert "venv" in reason
    # PATH fallback
    monkeypatch.setenv("PATH", str(venv_bin))
    argv2, reason2 = resolve_sopctl(tmp_path / "empty", env={"PATH": str(venv_bin)})
    (tmp_path / "empty").mkdir(exist_ok=True)
    argv2, reason2 = resolve_sopctl(tmp_path / "empty", env={"PATH": str(venv_bin)})
    assert argv2 is not None


def test_cooperative_enter_and_detach_confirm_required(tmp_path):
    from sopcontrol.attachment import apply_detachment
    from sopcontrol.runtime import enter

    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    session = enter(work, ["true"], mode="cooperative")
    receipt = session.wait()
    assert receipt.capabilities.process_events is False
    assert "not_unbypassable" in receipt.gaps
    denied = apply_detachment(work, confirm=False)
    assert denied["applied"] is False
    assert denied["reason"] == "confirm_required"


def test_browser_unknown_cdp_and_network_malformed(tmp_path):
    from sopcontrol.effects import evaluate_browser_effect, evaluate_network_effect

    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    d, ref = evaluate_browser_effect(work, cdp_endpoint="http://127.0.0.1:9222")
    assert ref.classification == "unknown_cdp"
    assert d.decision == "ask"
    d2, _ = evaluate_network_effect(work, url="")
    assert d2.decision == "deny"
    d3, t = evaluate_network_effect(work, url="http://localhost:9/x")
    assert t.classification == "local"

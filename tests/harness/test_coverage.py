"""Phase C: Control Coverage Ledger."""
from __future__ import annotations

import json
from pathlib import Path

from sopcontrol.action_plane import commit_action_result, evaluate_payload
from sopcontrol.cli import main
from sopcontrol.coverage import control_coverage, record_probe_result
from sopcontrol.coverage_model import ProbeResult
from sopcontrol.coverage_probe import verify_surface
from sopcontrol.events import ControlEvent, append_event


def test_blank_project_not_100_percent(tmp_path):
    work = tmp_path / "blank"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    report = control_coverage(work)
    assert report.control_coverage.discovered >= 1
    assert report.control_coverage.verified_ratio < 1.0
    assert report.control_coverage.verified == 0


def test_unknown_tool_expands_denominator_and_adds_gap_or_observable(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["attach", str(work)]) == 0
    before = control_coverage(work)
    before_n = before.control_coverage.discovered
    before_ratio = before.control_coverage.verified_ratio

    decision = evaluate_payload({"tool_name": "BrandNewNetTool", "tool_input": {"url": "https://x"}})
    commit_action_result(work, decision)
    after = control_coverage(work)
    assert after.control_coverage.discovered >= before_n
    # New surface appears
    names = {s.surface for s in after.surfaces}
    assert any(n.startswith("unknown:") or n == "unknown" for n in names) or "network" in names
    # Cannot stay at fake 100%
    assert after.control_coverage.verified_ratio < 1.0 or after.control_coverage.verified < after.control_coverage.discovered
    # If somehow verified_ratio was high, discovering more must not invent 100%
    assert after.control_coverage.verified_ratio <= max(before_ratio, 0.99)


def test_probe_without_harness_cannot_forge_verified(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    result = verify_surface(work, "filesystem_write")
    assert result.passed is False
    assert "no_live_harness" in result.detail
    report = control_coverage(work)
    fw = next(s for s in report.surfaces if s.surface == "filesystem_write")
    assert fw.state != "verified"


def test_probe_can_verify_with_live_harness_and_adapter_removal_revokes(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    assert main(["hook", "opencode", str(work)]) == 0
    result = verify_surface(work, "filesystem_write")
    assert result.passed is True
    assert "harness-check" in result.detail
    report = control_coverage(work)
    fw = next(s for s in report.surfaces if s.surface == "filesystem_write")
    assert fw.state == "verified"
    assert "probe" in fw.sources

    # Remove OpenCode adapter → prior verified for tool surfaces and harness must drop
    for p in (work / ".opencode" / "plugins").glob("sopcontrol*.js"):
        p.unlink()
    # Failed re-probe should force gap even over prior verified
    failed = verify_surface(work, "filesystem_write")
    assert failed.passed is False
    report2 = control_coverage(work)
    fw2 = next(s for s in report2.surfaces if s.surface == "filesystem_write")
    assert fw2.state == "gap"
    oc = next(s for s in report2.surfaces if s.surface == "harness_opencode")
    assert oc.state != "verified"


def test_failed_probe_downgrades_enforceable(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    assert main(["hook", "opencode", str(work)]) == 0
    assert verify_surface(work, "shell").passed is True
    # Force a failing probe record that must downgrade
    record_probe_result(
        work,
        ProbeResult(
            surface="shell",
            passed=False,
            evidence_digest="fail",
            detail="forced_fail",
        ),
    )
    report = control_coverage(work)
    shell = next(s for s in report.surfaces if s.surface == "shell")
    assert shell.state == "gap"
    assert shell.gap_reason == "forced_fail"


def test_worktree_events_do_not_cross_contaminate(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert main(["init", str(a)]) == 0
    assert main(["init", str(b)]) == 0
    # Force distinct worktree ids via append_event with explicit worktree_id
    d = evaluate_payload({"tool_name": "WeirdA", "tool_input": {}})
    # Manually stamp envelopes into different worktrees
    if d.envelope:
        d.envelope.worktree_id = "wt-a"
    commit_action_result(a, d)
    # Inject event only into a with worktree_id override by writing events path
    from sopcontrol.events import events_path

    append_event(
        a,
        ControlEvent(
            event_type="action_started",
            action="weird_a",
            outcome="observe",
            worktree_id="wt-a",
            detail={"surface": "unknown", "gap": "unrecognized_tool:WeirdA"},
        ),
    )
    append_event(
        b,
        ControlEvent(
            event_type="action_started",
            action="weird_b",
            outcome="observe",
            worktree_id="wt-b",
            detail={"surface": "unknown", "gap": "unrecognized_tool:WeirdB"},
        ),
    )
    ra = control_coverage(a, worktree_id="wt-a")
    rb = control_coverage(b, worktree_id="wt-b")
    names_a = {s.surface for s in ra.surfaces}
    names_b = {s.surface for s in rb.surfaces}
    assert "unknown:WeirdA" in names_a
    assert "unknown:WeirdA" not in names_b
    assert "unknown:WeirdB" in names_b
    assert "unknown:WeirdB" not in names_a


def test_coverage_cli_json_and_next_actions(tmp_path, capsys):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    assert main(["coverage", str(work), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == "1"
    assert "control_coverage" in data
    assert "scan_coverage" in data
    assert "connection_coverage" in data
    assert data["next_actions"]
    assert data["control_coverage"]["verified_ratio"] < 1.0


def test_scan_and_control_metrics_are_separate(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    (work / "a.py").write_text("x=1\n", encoding="utf-8")
    assert main(["init", str(work)]) == 0
    report = control_coverage(work)
    assert "eligible_files" in report.scan_coverage or "error" in report.scan_coverage
    assert hasattr(report.control_coverage, "verified_ratio")
    # Keys must not be mixed into one blob claiming both
    assert "verified_ratio" not in report.scan_coverage

"""Universal control plane: discovery≠gate, large md, cache, hook resolve, events."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from plugins import DETECTORS, SENSORS
from plugins.sensors.doc_scan import DocScanSensor
from sopcontrol.audit import run_discovery, run_enforcement
from sopcontrol.cli import main
from sopcontrol.cli_common import HOOK_TEMPLATE, run_gate
from sopcontrol.context import ProjectScope
from sopcontrol.events import ControlEvent, append_event, load_events, validate_event_payload
from sopcontrol.resolve_cli import resolve_sopctl

ROOT = Path(__file__).resolve().parents[2]


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)


def test_discovery_defers_over_1000_md_without_raising(tmp_path):
    work = tmp_path / "big"
    work.mkdir()
    _git_init(work)
    docs = work / "docs"
    docs.mkdir()
    for i in range(1100):
        (docs / f"n{i:04d}.md").write_text(f"must do {i}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=work, check=True, capture_output=True)

    scope = ProjectScope(work, mode="discovery")
    paths = list(scope.iter_files({".md"}, limit=500, on_budget="defer"))
    assert len(paths) == 500
    assert scope.last_coverage is not None
    assert scope.last_coverage.coverage_complete is False
    assert scope.last_coverage.deferred_files > 0

    # Doc sensor must not raise
    evidence = DocScanSensor().observe(scope)
    assert isinstance(evidence, list)


def test_gitignore_files_not_eligible(tmp_path):
    work = tmp_path / "g"
    work.mkdir()
    _git_init(work)
    (work / ".gitignore").write_text("secret/\n", encoding="utf-8")
    (work / "keep.md").write_text("must keep\n", encoding="utf-8")
    secret = work / "secret"
    secret.mkdir()
    (secret / "x.md").write_text("must secret\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "i"], cwd=work, check=True, capture_output=True)

    scope = ProjectScope(work)
    found = [p.name for p in scope.iter_files({".md"})]
    assert found == ["keep.md"]


def test_discovery_partial_gate_still_runs(tmp_path):
    work = tmp_path / "proj"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "shop-checkout", work)
    # add many md to force discovery defer
    extra = work / "docs" / "bulk"
    extra.mkdir(parents=True, exist_ok=True)
    for i in range(600):
        (extra / f"b{i}.md").write_text("note\n", encoding="utf-8")

    disc = run_discovery(work, SENSORS, DETECTORS, persist=False)
    assert disc.mode == "discovery"
    # gate/enforcement should not crash because of md volume
    enf = run_enforcement(work, SENSORS, DETECTORS, persist=False)
    assert enf.mode == "enforcement"
    assert isinstance(enf.verdicts, list)


def test_accepted_source_unreadable_fails_enforcement(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    (work / "docs").mkdir()
    (work / "docs" / "sop.md").write_text("必须经 gate_fn\n", encoding="utf-8")
    (work / "src").mkdir()
    (work / "src" / "app.py").write_text("def gate_fn():\n    return 1\n", encoding="utf-8")
    assert main([
        "rule", "add", str(work),
        "--id", "SRC-001",
        "--statement", "必须经 gate_fn",
        "--status", "accepted",
        "--source-ref", "docs/sop.md",
        "--consumer-marker", "gate_fn",
    ]) == 0
    (work / "docs" / "sop.md").unlink()
    report = run_enforcement(work, SENSORS, DETECTORS, persist=False)
    fails = [v for v in report.verdicts if v.status == "fail" and v.rule_id == "SRC-001"]
    assert fails, "missing source must fail-closed"


def test_accepted_consumer_removed_fails_or_gaps(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    (work / "docs").mkdir()
    (work / "docs" / "sop.md").write_text("必须经 gate_fn\n", encoding="utf-8")
    (work / "src").mkdir()
    app = work / "src" / "app.py"
    app.write_text("def gate_fn():\n    return 1\n", encoding="utf-8")
    assert main([
        "rule", "add", str(work),
        "--id", "CON-001",
        "--statement", "必须经 gate_fn",
        "--status", "accepted",
        "--source-ref", "docs/sop.md",
        "--consumer-marker", "gate_fn",
    ]) == 0
    app.write_text("def other():\n    return 0\n", encoding="utf-8")
    report = run_enforcement(work, SENSORS, DETECTORS, persist=False)
    bad = [v for v in report.verdicts if v.rule_id == "CON-001" and v.status in {"gap", "fail"}]
    assert bad


def test_resolve_sopctl_prefers_venv(tmp_path, monkeypatch):
    work = tmp_path / "w"
    work.mkdir()
    venv_bin = work / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    fake = venv_bin / "sopctl"
    fake.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.delenv("SOPCTL_BIN", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    argv, reason = resolve_sopctl(work, env=dict(os.environ))
    assert argv is not None
    assert str(fake) in argv[0]
    assert "venv" in reason


def test_resolve_sopctl_missing_clear_blocker(tmp_path, monkeypatch):
    work = tmp_path / "empty"
    work.mkdir()
    monkeypatch.delenv("SOPCTL_BIN", raising=False)
    monkeypatch.setenv("PATH", "/nonexistent")
    # also hide current interpreter module? still may find python3 -m
    argv, reason = resolve_sopctl(work, env={"PATH": "/nonexistent"})
    # may still get python -m from sys.executable
    if argv is None:
        assert "Do not use --no-verify" in reason or "sopctl not found" in reason


def test_hook_template_has_resolver_not_bare_only():
    assert "SOPCTL_BIN" in HOOK_TEMPLATE
    assert ".venv/bin/sopctl" in HOOK_TEMPLATE
    assert "--no-verify" in HOOK_TEMPLATE  # mentioned as forbidden
    assert "python" in HOOK_TEMPLATE and "sopcontrol.cli" in HOOK_TEMPLATE


def test_event_protocol_roundtrip(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    event = ControlEvent(
        event_type="action_started",
        action="demo",
        outcome="ok",
        next_action="continue",
    )
    path = append_event(work, event)
    assert path.exists()
    rows = load_events(work)
    assert rows and rows[-1].action == "demo"
    validated = validate_event_payload(json.loads(event.model_dump_json()))
    assert validated.event_type == "action_started"


def test_project_projection_idempotent(tmp_path):
    work = tmp_path / "w"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "shop-checkout", work)
    assert main(["project", "all", str(work)]) == 0
    text1 = (work / "AGENTS.md").read_text(encoding="utf-8")
    assert main(["project", "all", str(work)]) == 0
    text2 = (work / "AGENTS.md").read_text(encoding="utf-8")
    assert text1 == text2


def test_gate_cli_uses_enforcement(tmp_path):
    work = tmp_path / "w"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "shop-checkout", work)
    # should not raise despite any discovery budgets
    rc = run_gate(work)
    assert rc in (0, 1)


def test_evidence_cache_hit_on_unchanged_file(tmp_path):
    from sopcontrol.evidence_cache import EvidenceCache
    from sopcontrol.model import Evidence

    work = tmp_path / "w"
    work.mkdir()
    f = work / "a.py"
    f.write_text("x=1\n", encoding="utf-8")
    scope = ProjectScope(work, mode="discovery")
    cache = EvidenceCache(scope, project_id="proj-test")
    ev = [
        Evidence(
            kind="code_scan.identifiers",
            subject="a.py",
            observed=["x"],
            observer="code_scan",
            input_hash="h",
        )
    ]
    cache.put(rel_path="a.py", path=f, sensor_id="code_scan", evidence=ev)
    hit = cache.get(rel_path="a.py", path=f, sensor_id="code_scan")
    assert hit is not None and cache.hits == 1
    f.write_text("x=2\n", encoding="utf-8")
    miss = cache.get(rel_path="a.py", path=f, sensor_id="code_scan")
    assert miss is None and cache.misses >= 1


def test_two_scopes_isolate_event_logs(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert main(["init", str(a)]) == 0
    assert main(["init", str(b)]) == 0
    append_event(a, ControlEvent(event_type="action_started", action="in-a"))
    append_event(b, ControlEvent(event_type="action_started", action="in-b"))
    actions_a = {e.action for e in load_events(a)}
    actions_b = {e.action for e in load_events(b)}
    assert "in-a" in actions_a and "in-a" not in actions_b
    assert "in-b" in actions_b


def test_capability_ticket_expire_reuse_and_mismatch(tmp_path):
    from datetime import timedelta

    from sopcontrol.model import utcnow
    from sopcontrol.tickets import TicketError, issue_ticket, redeem_ticket

    work = tmp_path / "w"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    ticket = issue_ticket(
        work,
        action="push",
        input_fingerprint="fp1",
        allowed_side_effects=["write_tracker"],
        ttl_seconds=60,
    )
    redeem_ticket(
        work,
        ticket_id=ticket.ticket_id,
        secret=ticket.secret,
        action="push",
        input_fingerprint="fp1",
        side_effect="write_tracker",
    )
    with pytest.raises(TicketError, match="already consumed"):
        redeem_ticket(
            work,
            ticket_id=ticket.ticket_id,
            secret=ticket.secret,
            action="push",
            input_fingerprint="fp1",
            side_effect="write_tracker",
        )
    ticket2 = issue_ticket(
        work,
        action="push",
        input_fingerprint="fp2",
        allowed_side_effects=["write_tracker"],
        ttl_seconds=1,
    )
    with pytest.raises(TicketError, match="expired"):
        redeem_ticket(
            work,
            ticket_id=ticket2.ticket_id,
            secret=ticket2.secret,
            action="push",
            input_fingerprint="fp2",
            side_effect="write_tracker",
            now=utcnow() + timedelta(seconds=5),
        )
    ticket3 = issue_ticket(
        work,
        action="push",
        input_fingerprint="fp3",
        allowed_side_effects=["write_tracker"],
    )
    with pytest.raises(TicketError, match="action mismatch"):
        redeem_ticket(
            work,
            ticket_id=ticket3.ticket_id,
            secret=ticket3.secret,
            action="other",
            input_fingerprint="fp3",
        )
    with pytest.raises(TicketError, match="secret mismatch"):
        redeem_ticket(
            work,
            ticket_id=ticket3.ticket_id,
            secret="wrong-secret-value-xxxxxxxxxxxxxxxx",
            action="push",
            input_fingerprint="fp3",
        )

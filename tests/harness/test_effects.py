"""Phase E: network/browser/credential/db/background/idempotent effect primitives."""
from __future__ import annotations

import json
from pathlib import Path

from sopcontrol.adapters.effects.browser import classify_browser_session
from sopcontrol.adapters.effects.network import classify_network_target
from sopcontrol.cli import main
from sopcontrol.coverage import control_coverage
from sopcontrol.effects import (
    evaluate_browser_effect,
    evaluate_network_effect,
    grant_credential,
    idempotent_external_write,
    register_background_effect,
    summarize_db_write,
)
from sopcontrol.events import load_events
from sopcontrol.tickets import TicketError, redeem_ticket


def test_network_classification_and_decision(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    t = classify_network_target("https://api.example.com/v1/x", method="POST")
    assert t.host == "api.example.com"
    assert t.classification == "unknown_host"
    assert t.target_digest

    d, target = evaluate_network_effect(
        work, url="https://api.example.com/v1/x", allow_hosts=["api.example.com"],
    )
    assert target.classification == "allowlist_candidate"
    assert d.decision == "allow"

    d2, _ = evaluate_network_effect(work, url="file:///etc/passwd")
    assert d2.decision == "deny"


def test_network_ticket_redeem(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    # issue via CLI
    assert main([
        "effect", "issue-network-ticket", str(work),
        "--url", "https://hooks.example.com/a", "--show-secret",
    ]) == 0
    # get fingerprint from classify
    target = classify_network_target("https://hooks.example.com/a")
    # load ticket id from disk
    tickets = list((work / ".sopcontrol-local").rglob("tkt-*.json"))
    assert tickets
    data = json.loads(tickets[0].read_text(encoding="utf-8"))
    d, _ = evaluate_network_effect(
        work,
        url="https://hooks.example.com/a",
        require_ticket=True,
        ticket_id=data["ticket_id"],
        ticket_secret=data["secret"],
    )
    assert d.decision == "allow"
    # reuse fails
    d2, _ = evaluate_network_effect(
        work,
        url="https://hooks.example.com/a",
        require_ticket=True,
        ticket_id=data["ticket_id"],
        ticket_secret=data["secret"],
    )
    assert d2.decision == "deny"


def test_browser_human_challenge_asks(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    d, ref = evaluate_browser_effect(
        work, action="cloudflare", page_url="https://jobs.example.com/x",
        profile_label="main", approved_profiles=["main"],
    )
    assert ref.classification == "human_challenge"
    assert ref.reuses_approved_chrome is True
    assert d.decision == "ask"
    assert "human_challenge" in d.gap


def test_browser_approved_profile_allows(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    d, ref = evaluate_browser_effect(
        work, profile_label="MainChrome", approved_profiles=["mainchrome"],
        page_url="https://example.com",
    )
    assert ref.classification == "approved_profile"
    assert d.decision == "allow"


def test_credential_grant_no_secret_in_events(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    decision, grant, ticket = grant_credential(
        work, scope=["cookies:jobsdb"], input_fingerprint="fp1", ttl_seconds=60,
    )
    assert grant.ticket_id == ticket.ticket_id
    assert ticket.secret
    events = load_events(work)
    blob = json.dumps([e.model_dump(mode="json") for e in events])
    assert ticket.secret not in blob
    # redeem works once
    redeem_ticket(
        work,
        ticket_id=ticket.ticket_id,
        secret=ticket.secret,
        action="credential.use",
        input_fingerprint="fp1",
        side_effect="use_credential:cookies:jobsdb",
    )
    try:
        redeem_ticket(
            work,
            ticket_id=ticket.ticket_id,
            secret=ticket.secret,
            action="credential.use",
            input_fingerprint="fp1",
            side_effect="use_credential:cookies:jobsdb",
        )
        assert False, "should not reuse"
    except TicketError:
        pass


def test_db_summary_and_background_and_idempotent(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    d, summary = summarize_db_write(
        work, engine="sqlite", operation="insert", object_name="jobs", row_count=3,
    )
    assert d.decision == "observe"
    assert summary.row_count == 3
    assert summary.object_digest

    d2, reg = register_background_effect(
        work, kind="queue", command_summary="worker consume", pid=999,
    )
    assert reg.registry_id.startswith("bg-")
    assert d2.kind == "background"

    r1 = idempotent_external_write(
        work, idempotency_key="push-1", action="portal.push", result_digest="r1",
    )
    assert r1.outcome == "accepted"
    r2 = idempotent_external_write(
        work, idempotency_key="push-1", action="portal.push", result_digest="r1",
    )
    assert r2.outcome == "duplicate"


def test_coverage_lists_effect_surfaces(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    report = control_coverage(work)
    names = {s.surface for s in report.surfaces}
    for s in ("network", "browser", "credential", "database", "background"):
        assert s in names
        rec = next(x for x in report.surfaces if x.surface == s)
        assert rec.state != "verified"


def test_effect_cli_network_json(tmp_path, capsys):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    assert main([
        "effect", "network", str(work), "--url", "https://example.com", "--json",
    ]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["target"]["host"] == "example.com"
    assert data["decision"]["kind"] == "network"

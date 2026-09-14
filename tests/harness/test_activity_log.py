"""Activity log: schema compat, redaction, health, CLI, integrity, append cost."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from sopcontrol.activity_log import (
    activity_health,
    aggregate_run_report,
    append_activity,
    benchmark_append,
    build_event,
    load_activity,
    record_activity,
    redact_text,
    render_report_markdown,
    sanitize_detail,
    write_run_report,
)
from sopcontrol.cli import main
from sopcontrol.context import ProjectScope
from sopcontrol.events import ControlEvent, append_event, events_path, load_events, validate_event_payload


def _init(tmp_path: Path) -> Path:
    assert main(["init", str(tmp_path)]) == 0
    return tmp_path


def _events_file(root: Path) -> Path:
    wt = ProjectScope(root, mode="discovery").worktree_id
    path = events_path(root, wt)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_v1_schema_readable_with_defaults(tmp_path):
    root = _init(tmp_path)
    path = _events_file(root)
    legacy = {
        "schema_version": "1",
        "event_type": "action_started",
        "action": "scan",
        "outcome": "ok",
        "observed_at": "2026-09-01T00:00:00+00:00",
        "detail": {"surface": "cli"},
    }
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    rows = load_events(root)
    assert len(rows) == 1
    event = rows[0]
    assert event.schema_version == "1"
    assert event.source == "runtime"
    assert event.confidence in {"observed", "unknown"}
    assert event.event_id.startswith("cev-")
    # Must not rewrite the on-disk legacy row.
    on_disk = path.read_text(encoding="utf-8").strip()
    assert '"schema_version": "1"' in on_disk or '"schema_version":"1"' in on_disk
    assert "record_digest" not in on_disk


def test_v2_roundtrip_and_stable_digests(tmp_path):
    root = _init(tmp_path)
    event = build_event(
        "gate_evaluated",
        action="materials.apply",
        run_id="run-1",
        operation_id="op-1",
        decision="allow",
        outcome="allow",
        source="runtime",
        confidence="verified",
        rule_ids=["JF-MAT-001"],
        detail={"selected_rule_count": 1, "surface": "workflow"},
    )
    result = append_activity(root, event)
    assert result.ok and result.event is not None
    loaded = load_activity(root, run_id="run-1")
    assert len(loaded.events) == 1
    again = loaded.events[0]
    assert again.event_id == result.event.event_id
    assert again.record_digest == result.event.record_digest
    assert loaded.digest_mismatch == 0
    assert loaded.logging_status == "healthy"


def test_redaction_negative_secret_never_persisted(tmp_path):
    root = _init(tmp_path)
    secret = "sk-SUPERSECRETVALUE999"
    detail = {
        "surface": "cli",
        "stdout_tail": f"ok token={secret}",
        "stderr_tail": f"Authorization: Bearer {secret}",
        "prompt": "full JD text must not appear",
        "api_key": secret,
        "ticket_id": "tkt-abc",
        "blockers": ["x"],
    }
    # Unknown business key should be dropped by allowlist.
    detail["jd_text"] = "Senior engineer role with salary"
    result = record_activity(
        root,
        "operation_finished",
        action="apply",
        run_id="run-sec",
        operation_id="op-sec",
        source="adapter",
        confidence="observed",
        outcome="passed",
        detail=detail,
    )
    assert result.ok
    raw = (result.path or Path()).read_text(encoding="utf-8")
    assert secret not in raw
    assert "Senior engineer" not in raw
    assert "full JD text" not in raw
    assert "tkt-abc" in raw
    report = aggregate_run_report(load_activity(root, run_id="run-sec").events, run_id="run-sec")
    blob = json.dumps(report) + render_report_markdown(report)
    assert secret not in blob
    assert "Senior engineer" not in blob


def test_declared_completed_not_counted_verified(tmp_path):
    root = _init(tmp_path)
    record_activity(
        root,
        "action_completed",
        action="push",
        run_id="run-d",
        operation_id="op-d",
        source="declared",
        confidence="declared",
        outcome="ok",
    )
    record_activity(
        root,
        "gate_evaluated",
        action="push",
        run_id="run-d",
        operation_id="op-d",
        source="runtime",
        confidence="verified",
        decision="deny",
        outcome="deny",
    )
    report = aggregate_run_report(load_activity(root, run_id="run-d").events, run_id="run-d")
    assert report["coverage"]["blocked_units"] >= 1
    assert report["status"] == "blocked"
    # Declared completion must not inflate verified.
    assert "op-d" in report["unproven"] or report["coverage"]["unproven_units"] >= 1


def test_health_detects_invalid_and_mismatch(tmp_path):
    root = _init(tmp_path)
    record_activity(
        root,
        "request_received",
        action="x",
        run_id="run-h",
        operation_id="op-h",
        confidence="observed",
    )
    path = _events_file(root)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{not-json\n")
        fh.write(json.dumps({
            "schema_version": "2",
            "event_type": "gate_evaluated",
            "action": "x",
            "run_id": "run-h",
            "operation_id": "op-h",
            "source": "runtime",
            "confidence": "verified",
            "decision": "allow",
            "outcome": "allow",
            "observed_at": "2026-09-14T00:00:00+00:00",
            "event_id": "cev-tampered",
            "record_digest": "sha256:deadbeef",
            "detail": {},
            "cost": {},
            "learning": {},
        }) + "\n")
    health = activity_health(root)
    assert health.status == "degraded"
    assert health.invalid_lines >= 1
    assert health.digest_mismatch >= 1


def test_cli_log_smoke(tmp_path, capsys):
    root = _init(tmp_path)
    capsys.readouterr()
    record_activity(
        root,
        "gate_evaluated",
        action="scan",
        run_id="run-cli",
        operation_id="op-cli",
        source="runtime",
        confidence="verified",
        decision="allow",
        outcome="allow",
        rule_ids=["JF-SCAN-001"],
    )
    assert main(["log", "list", str(root), "--run-id", "run-cli"]) == 0
    out = capsys.readouterr().out
    assert "gate_evaluated" in out
    assert main(["log", "show", str(root), "--run-id", "run-cli"]) == 0
    assert main(["log", "report", str(root), "--run-id", "run-cli", "--format", "markdown"]) == 0
    report_out = capsys.readouterr().out
    assert "SOP Control Run Report" in report_out
    assert main(["log", "health", str(root)]) == 0
    assert main(["log", "benchmark", str(root), "--count", "20"]) == 0


def test_concurrent_appends_are_complete_lines(tmp_path):
    root = _init(tmp_path)
    errors: list[str] = []

    def worker(n: int) -> None:
        for i in range(30):
            result = record_activity(
                root,
                "request_received",
                action="conc",
                run_id="run-c",
                operation_id=f"op-{n}-{i}",
                sequence=i,
                confidence="observed",
            )
            if not result.ok:
                errors.append(result.error)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    path = _events_file(root)
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 120
    for line in lines:
        json.loads(line)  # no partial lines


def test_append_benchmark_budget(tmp_path):
    root = _init(tmp_path)
    result = benchmark_append(root, count=50)
    assert result["ok"]
    # Handbook target is p95 ≤ 5ms; allow CI noise up to 25ms hard fail.
    assert result["p95_ms"] < 25.0, result
    assert "within_budget" in result


def test_validate_event_payload_accepts_new_fields():
    event = validate_event_payload({
        "event_type": "ticket_redeemed",
        "action": "push",
        "source": "runtime",
        "confidence": "verified",
        "operation_id": "op-1",
        "cost": {"admit_count": 1},
    })
    assert event.operation_id == "op-1"
    assert event.cost.admit_count == 1


def test_sanitize_detail_drops_unknown_and_redacts():
    out = sanitize_detail({
        "ticket_id": "tkt-1",
        "secret": "abc",
        "business_essay": "should drop",
        "stdout_tail": "Bearer sk-ABCDEFGHIJKLMN",
    })
    assert out["ticket_id"] == "tkt-1"
    assert "business_essay" not in out
    assert "secret" not in out  # secret-named keys are not allowlisted
    blob = json.dumps(out)
    assert "sk-ABCDEFGHIJKLMN" not in blob
    assert "<redacted>" in blob


def test_append_event_delegates_and_compat(tmp_path):
    root = _init(tmp_path)
    path = append_event(
        root,
        ControlEvent(event_type="action_started", action="legacy-path", outcome="ok"),
    )
    assert path.exists()
    rows = load_events(root)
    assert any(r.action == "legacy-path" for r in rows)
    assert any(r.event_id.startswith("cev-") for r in rows)


def test_write_report_has_no_side_effect_on_events(tmp_path):
    root = _init(tmp_path)
    record_activity(
        root,
        "run_finished",
        action="scan",
        run_id="run-r",
        confidence="observed",
        outcome="ok",
    )
    path = _events_file(root)
    before = path.read_text(encoding="utf-8")
    report = aggregate_run_report(load_activity(root, run_id="run-r").events, run_id="run-r")
    write_run_report(root, report, fmt="markdown")
    after = path.read_text(encoding="utf-8")
    assert before == after
    assert (root / ".sopcontrol-local" / "reports" / "run-run-r.md").is_file()


def test_redact_text_masks_home_and_email():
    text = "see /Users/alice/project and bob@example.com"
    out = redact_text(text)
    assert "/Users/alice" not in out
    assert "bob@example.com" not in out


def test_top_level_free_text_fields_are_redacted(tmp_path):
    root = _init(tmp_path)
    secret = "sk-TOPLEVELSECRET999"
    result = record_activity(
        root,
        "action_completed",
        action=f"run with {secret}",
        run_id="run-top",
        operation_id="op-top",
        source="runtime",
        confidence="observed",
        outcome="ok",
        blocker=f"token={secret}",
        next_action=f"see /Users/alice/secret and {secret}",
        phase="apply",
        decision="allow",
        state_before=f"Bearer {secret}",
        state_after="done",
    )
    assert result.ok and result.event is not None
    raw = (result.path or Path()).read_text(encoding="utf-8")
    assert secret not in raw
    assert "/Users/alice" not in raw
    assert "<redacted>" in raw or "<redacted-home>" in raw
    assert secret not in result.event.blocker
    assert secret not in result.event.next_action
    assert secret not in result.event.action
    assert secret not in result.event.state_before


def test_fake_completed_and_cli_forged_verified_not_counted(tmp_path):
    root = _init(tmp_path)
    # Declared/self-reported completion must not inflate verified.
    record_activity(
        root,
        "action_completed",
        action="push",
        run_id="run-fake",
        operation_id="op-fake",
        source="declared",
        confidence="declared",
        outcome="ok",
    )
    # CLI-forged verified completion is also untrusted.
    record_activity(
        root,
        "action_completed",
        action="push",
        run_id="run-fake",
        operation_id="op-cli",
        source="cli",
        confidence="verified",
        outcome="ok",
    )
    # Gate allow alone is not executed/verified completion.
    record_activity(
        root,
        "gate_evaluated",
        action="push",
        run_id="run-fake",
        operation_id="op-gate",
        source="runtime",
        confidence="verified",
        decision="allow",
        outcome="allow",
    )
    # Real runtime completion with evidence does count.
    record_activity(
        root,
        "operation_finished",
        action="push",
        run_id="run-fake",
        operation_id="op-real",
        source="runtime",
        confidence="verified",
        outcome="passed",
        evidence_ids=["ev-1"],
    )
    report = aggregate_run_report(
        load_activity(root, run_id="run-fake").events, run_id="run-fake",
    )
    assert report["coverage"]["eligible_units"] == "unknown"
    assert report["rates"]["coverage_status"] == "partial_observation"
    assert report["rates"]["gate_coverage"] is None
    assert report["coverage"]["verified_units"] == 1
    assert report["coverage"]["executed_units"] == 1
    assert "op-fake" in report["unproven"] or report["coverage"]["unproven_units"] >= 1
    assert "op-cli" in report["unproven"] or report["coverage"]["unproven_units"] >= 2


def test_digest_mismatch_excluded_from_verified(tmp_path):
    root = _init(tmp_path)
    path = _events_file(root)
    path.write_text(
        json.dumps({
            "schema_version": "2",
            "event_type": "action_completed",
            "action": "push",
            "run_id": "run-mm",
            "operation_id": "op-mm",
            "source": "runtime",
            "confidence": "verified",
            "outcome": "ok",
            "observed_at": "2026-09-14T00:00:00+00:00",
            "event_id": "cev-mismatch",
            "record_digest": "sha256:deadbeef",
            "detail": {},
            "cost": {},
            "learning": {},
            "rule_ids": [],
            "evidence_ids": ["ev-x"],
            "artifact_digests": [],
        }) + "\n",
        encoding="utf-8",
    )
    loaded = load_activity(root, run_id="run-mm")
    assert loaded.digest_mismatch >= 1
    assert "cev-mismatch" in loaded.untrusted_event_ids
    report = aggregate_run_report(loaded.events, run_id="run-mm")
    assert report["coverage"]["verified_units"] == 0
    assert report["coverage"]["executed_units"] == 0
    health = activity_health(root)
    assert health.status == "degraded"


def test_eligible_unknown_without_inventory(tmp_path):
    root = _init(tmp_path)
    for i in range(3):
        record_activity(
            root,
            "gate_evaluated",
            action="scan",
            run_id="run-el",
            operation_id=f"op-{i}",
            source="runtime",
            confidence="verified",
            decision="allow",
            outcome="allow",
        )
        record_activity(
            root,
            "operation_finished",
            action="scan",
            run_id="run-el",
            operation_id=f"op-{i}",
            source="runtime",
            confidence="verified",
            outcome="passed",
        )
    report = aggregate_run_report(
        load_activity(root, run_id="run-el").events, run_id="run-el",
    )
    assert report["coverage"]["eligible_units"] == "unknown"
    assert report["coverage"]["eligible_status"] == "partial_observation"
    assert report["rates"]["coverage_status"] == "partial_observation"
    assert report["rates"]["gate_coverage"] is None
    assert report["rates"]["evidence_completeness"] is None
    # With explicit inventory, rates become computable.
    with_inv = aggregate_run_report(
        load_activity(root, run_id="run-el").events,
        run_id="run-el",
        eligible_units=10,
    )
    assert with_inv["coverage"]["eligible_units"] == 10
    assert with_inv["rates"]["coverage_status"] == "inventory"
    assert with_inv["rates"]["gate_coverage"] is not None


def test_health_not_healthy_on_log_degraded(tmp_path):
    root = _init(tmp_path)
    record_activity(
        root,
        "log_degraded",
        action="activity_log.append",
        source="system",
        confidence="unknown",
        outcome="degraded",
        detail={"logging_status": "degraded", "error_class": "OSError"},
    )
    health = activity_health(root)
    assert health.status == "degraded"
    assert health.log_degraded_events >= 1


def test_append_benchmark_reports_production_path(tmp_path):
    root = _init(tmp_path)
    # Warm identity / path resolution so the measured window is steady-state.
    assert record_activity(
        root, "request_received", action="warmup", confidence="unknown",
    ).ok
    result = benchmark_append(root, count=30, include_production_path=True)
    assert result["ok"]
    assert "production" in result
    assert result["production"]["p95_ms"] is not None
    assert result["direct"]["p95_ms"] is not None
    # Direct append: handbook ≤5ms, CI noise budget 25ms.
    assert result["p95_ms"] < 25.0, result
    # Production path includes identity/git work and is much slower than the
    # micro-benchmark. Assert honesty (prod >= direct) and a realistic ceiling.
    assert result["production"]["p95_ms"] >= result["direct"]["p95_ms"]
    assert result["production"]["p95_ms"] < 500.0, result

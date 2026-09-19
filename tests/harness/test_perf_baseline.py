"""WP-G measurements and WP-K reference-host smoke checks.

This file is deliberately self-contained.  Every benchmark uses a temporary
project, performs a warm-up, then records at least 100 valid samples.  The
reported counters describe the control-plane path exercised by the benchmark;
the I/O counter is a Python-level ``open``/``os.open``/replace delta rather
than a claim about kernel syscalls.

The fixtures are reference hosts, not JobsFlow evidence.  Their smoke checks
only prove that the adapter seam can be called from a small local host.
"""
from __future__ import annotations

import builtins
import contextlib
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from sopcontrol.action_plane import build_envelope, evaluate_action
from sopcontrol.attachment import attachment_status
from sopcontrol.cli import build_parser, main
from sopcontrol.control_profile import (
    freeze_profile,
    load_frozen,
    normalize_profile,
    save_draft,
)
from sopcontrol.dynamic_sop import select_rules
from sopcontrol.model import (
    ActivationSelector,
    Flexibility,
    Modality,
    Rule,
    RuleStatus,
    SourceRef,
)
from sopcontrol.registry import Registry
from sopcontrol.surface_inventory import refresh_inventory
from sopcontrol.tickets import (
    issue_phase_grant,
    issue_ticket,
    redeem_ticket,
    verify_ticket_for_admission,
)


ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / ".venv" / "bin" / "python"
SAMPLES = max(100, int(os.environ.get("SOPCONTROL_PERF_SAMPLES", "100")))
HOST_CLI = ROOT / "corpus" / "fixtures" / "reference-host-cli" / "host_cli.py"
HOST_WORKER = ROOT / "corpus" / "fixtures" / "reference-host-worker" / "host_worker.py"


def _zero_cost() -> dict[str, int]:
    return {
        "llm_calls": 0,
        "ticket_issued": 0,
        "ticket_redeemed": 0,
        "grant_count": 0,
        "receipt_bytes": 0,
    }


class _IOCounter:
    """Count high-level file opens during in-process benchmark operations."""

    def __init__(self) -> None:
        self.reads = 0
        self.writes = 0
        self._originals: dict[str, object] = {}

    def __enter__(self) -> "_IOCounter":
        self._originals = {
            "builtins.open": builtins.open,
            "io.open": io.open,
            "os.open": os.open,
            "os.replace": os.replace,
            "os.unlink": os.unlink,
        }
        original_builtin_open = builtins.open
        original_io_open = io.open
        original_os_open = os.open
        original_os_replace = os.replace
        original_os_unlink = os.unlink

        def counted_open(file, mode="r", *args, **kwargs):
            mode_text = str(mode)
            if "r" in mode_text or "+" in mode_text:
                self.reads += 1
            if any(flag in mode_text for flag in ("w", "a", "x", "+")):
                self.writes += 1
            return original_builtin_open(file, mode, *args, **kwargs)

        def counted_io_open(file, mode="r", *args, **kwargs):
            mode_text = str(mode)
            if "r" in mode_text or "+" in mode_text:
                self.reads += 1
            if any(flag in mode_text for flag in ("w", "a", "x", "+")):
                self.writes += 1
            return original_io_open(file, mode, *args, **kwargs)

        def counted_os_open(path, flags, *args, **kwargs):
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                self.writes += 1
            else:
                self.reads += 1
            return original_os_open(path, flags, *args, **kwargs)

        def counted_replace(src, dst, *args, **kwargs):
            self.writes += 1
            return original_os_replace(src, dst, *args, **kwargs)

        def counted_unlink(path, *args, **kwargs):
            self.writes += 1
            return original_os_unlink(path, *args, **kwargs)

        builtins.open = counted_open
        io.open = counted_io_open
        os.open = counted_os_open
        os.replace = counted_replace
        os.unlink = counted_unlink
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        builtins.open = self._originals["builtins.open"]  # type: ignore[assignment]
        io.open = self._originals["io.open"]  # type: ignore[assignment]
        os.open = self._originals["os.open"]  # type: ignore[assignment]
        os.replace = self._originals["os.replace"]  # type: ignore[assignment]
        os.unlink = self._originals["os.unlink"]  # type: ignore[assignment]


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = max(0, math.ceil(len(ordered) * quantile) - 1)
    return ordered[position]


def _measure(
    label: str,
    operation: Callable[[], dict[str, int]],
    *,
    track_io: bool = True,
    warmups: int = 5,
) -> dict[str, object]:
    for _ in range(warmups):
        operation()

    elapsed_ms: list[float] = []
    costs: list[dict[str, int]] = []
    tracker = _IOCounter() if track_io else None
    context = tracker if tracker is not None else contextlib.nullcontext()
    with context:
        for _ in range(SAMPLES):
            started = time.perf_counter()
            cost = operation()
            elapsed_ms.append((time.perf_counter() - started) * 1000.0)
            costs.append(cost)

    totals: dict[str, int] = {}
    for cost in costs:
        for key, value in cost.items():
            totals[key] = totals.get(key, 0) + int(value)
    result: dict[str, object] = {
        "label": label,
        "samples": len(elapsed_ms),
        "warmups": warmups,
        "p50_ms": round(_percentile(elapsed_ms, 0.50), 3),
        "p95_ms": round(_percentile(elapsed_ms, 0.95), 3),
        "min_ms": round(min(elapsed_ms), 3),
        "max_ms": round(max(elapsed_ms), 3),
        "cost_totals": totals,
        "cost_per_sample": {
            key: round(value / len(elapsed_ms), 3) for key, value in totals.items()
        },
        "file_io": {
            "reads": tracker.reads if tracker is not None else None,
            "writes": tracker.writes if tracker is not None else None,
            "scope": (
                "Python-level open/os.open/replace/unlink deltas"
                if tracker is not None
                else "child process I/O not instrumented"
            ),
        },
    }
    return result


def _init_project(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with contextlib.redirect_stdout(io.StringIO()):
        assert main(["init", str(root)]) == 0


def _prepare_state_project(root: Path) -> str:
    _init_project(root)
    (root / "README.md").write_text("performance fixture\n", encoding="utf-8")
    profile = normalize_profile(
        {
            "profile_id": "perf-profile",
            "scope": {"project": "perf-fixture", "task": "TASK-PERF", "phase": "audit"},
            "checks": {"required": ["jd_fit"], "modes": {"jd_fit": "required"}},
            "baseline": {"source_ref": "perf-baseline", "generation_mode": "authoritative"},
            "repair": {"max_rounds": 1},
            "budget": {"max_audit_calls": 1, "max_repair_calls": 1},
            "stop_when": ["pass"],
        }
    )
    save_draft(root, profile)
    frozen = freeze_profile(root, profile.profile_id)
    assert frozen.digest
    return frozen.digest


def _perf_rules() -> list[Rule]:
    return [
        Rule(
            rule_id="PERF-READ-001",
            statement="性能 fixture 的读取动作必须经过普通 admission。",
            modality=Modality.MUST,
            status=RuleStatus.accepted,
            activation=ActivationSelector(actions=["read"], phases=["audit"]),
            flexibility=Flexibility(allowed_variance="fixture-only"),
            source=SourceRef(type="manual_seed", ref="tests/harness/test_perf_baseline.py"),
            consumer_markers=["perf_admission"],
        )
    ]


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + current if current else "")
    return env


def _test_perf_baseline(tmp_path: Path) -> list[dict[str, object]]:
    rules = _perf_rules()
    envelope = build_envelope(
        {"tool_name": "Read", "tool_input": {"file_path": "README.md"}},
        harness="perf",
    )

    def pure_admission() -> dict[str, int]:
        selected, not_applicable, unproven = select_rules(
            rules, {"action": "read", "phase": "audit", "product": "perf-fixture"}
        )
        assert selected and not not_applicable and not unproven
        decision = evaluate_action(envelope, session_intent="execute")
        assert decision.decision in {"allow", "observe"}
        return _zero_cost()

    ordinary_root = tmp_path / "ordinary-action"
    plan_digest = _prepare_state_project(ordinary_root)
    payload = json.dumps(
        {
            "tool_name": "Read",
            "tool_input": {
                "file_path": "README.md",
                "control_profile_id": "perf-profile",
                "effective_plan_digest": plan_digest,
            },
        },
        ensure_ascii=False,
    )

    def ordinary_action() -> dict[str, int]:
        registry_path = ordinary_root / ".sopcontrol" / "rules" / "registry.yaml"
        assert Registry(registry_path).load() == []
        current = load_frozen(ordinary_root, "perf-profile", 1)
        assert current.digest == plan_digest
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            assert main(["harness-check", str(ordinary_root), "--payload", payload]) == 0
        result = json.loads(output.getvalue().strip().splitlines()[-1])
        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
        return _zero_cost()

    phase_root = tmp_path / "phase-grant"
    _init_project(phase_root)

    def phase_grant() -> dict[str, int]:
        grant = issue_phase_grant(
            phase_root,
            phase="audit",
            allowed_side_effects=["external_write"],
            task_id="TASK-PERF",
            operation="op-perf-phase",
            allowed_actions=["step.one", "step.two"],
            ttl_seconds=600,
        )
        for action in ("step.one", "step.two"):
            checked = verify_ticket_for_admission(
                phase_root,
                ticket_id=grant.ticket_id,
                secret=grant.secret,
                action=action,
                input_fingerprint=grant.input_fingerprint,
                side_effect="external_write",
                task_id="TASK-PERF",
                expected_phase="audit",
                expected_operation_id="op-perf-phase",
            )
            assert checked["verified"] is True and checked["consumed"] is False
        redeemed = redeem_ticket(
            phase_root,
            ticket_id=grant.ticket_id,
            secret=grant.secret,
            action="step.one",
            input_fingerprint=grant.input_fingerprint,
            side_effect="external_write",
            task_id="TASK-PERF",
            expected_phase="audit",
            expected_operation_id="op-perf-phase",
        )
        assert redeemed.consumed_at is not None
        return {
            "llm_calls": 0,
            "ticket_issued": 1,
            "ticket_redeemed": 1,
            "grant_count": 1,
            "receipt_bytes": 0,
        }

    ticket_root = tmp_path / "capability-ticket"
    _init_project(ticket_root)

    def capability_ticket() -> dict[str, int]:
        ticket = issue_ticket(
            ticket_root,
            action="credential.use",
            input_fingerprint="perf-secretless-input",
            allowed_side_effects=["use_credential:fixture"],
            ttl_seconds=600,
        )
        consumed = redeem_ticket(
            ticket_root,
            ticket_id=ticket.ticket_id,
            secret=ticket.secret,
            action="credential.use",
            input_fingerprint="perf-secretless-input",
            side_effect="use_credential:fixture",
        )
        assert consumed.consumed_at is not None
        return {
            "llm_calls": 0,
            "ticket_issued": 1,
            "ticket_redeemed": 1,
            "grant_count": 0,
            "receipt_bytes": 0,
        }

    def cold_start() -> dict[str, int]:
        process = subprocess.run(
            [str(PYTHON), "-m", "sopcontrol.cli", "--help"],
            cwd=ROOT,
            env=_subprocess_env(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert process.returncode == 0 and "usage:" in process.stdout.lower()
        return _zero_cost()

    def warm_start() -> dict[str, int]:
        assert build_parser().prog == "sopctl"
        return _zero_cost()

    attach_root = tmp_path / "attach"
    _init_project(attach_root)

    def attach() -> dict[str, int]:
        with contextlib.redirect_stdout(io.StringIO()):
            assert main(["attach", str(attach_root)]) == 0
        return _zero_cost()

    def attach_status() -> dict[str, int]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            assert main(["attach-status", str(attach_root), "--json"]) == 0
        status = json.loads(output.getvalue())
        assert status["connected"] is True
        return _zero_cost()

    scan_root = tmp_path / "incremental-scan"
    _init_project(scan_root)
    (scan_root / "pyproject.toml").write_text(
        "[project]\nname = 'perf-fixture'\nversion = '0.1.0'\n"
        "[project.scripts]\nperf-cli = 'perf:main'\n",
        encoding="utf-8",
    )
    (scan_root / "bin").mkdir()
    report_script = scan_root / "bin" / "report.sh"
    report_script.write_text("#!/bin/sh\necho report\n", encoding="utf-8")
    report_script.chmod(0o755)
    with contextlib.redirect_stdout(io.StringIO()):
        assert main(["surface", "refresh", str(scan_root)]) == 0
    assert refresh_inventory(scan_root)["reused"] is True

    def incremental_scan() -> dict[str, int]:
        result = refresh_inventory(scan_root)
        assert result["reused"] is True and result["new"] == 0
        return _zero_cost()

    reports = [
        _measure("pure_select_evaluate", pure_admission),
        _measure("harness_check_local_state", ordinary_action),
        _measure("phase_grant_issue_verify_redeem", phase_grant),
        _measure("capability_ticket_issue_redeem", capability_ticket),
        _measure("cold_start_sopctl_help", cold_start, track_io=False),
        _measure("warm_start_parser", warm_start),
        _measure("attach", attach),
        _measure("attach_status", attach_status),
        _measure("incremental_surface_scan", incremental_scan),
    ]
    for report in reports:
        totals = report["cost_totals"]
        assert isinstance(totals, dict) and totals.get("llm_calls", 0) == 0
        assert report["samples"] >= 100
        print("PERF_BASELINE " + json.dumps(report, ensure_ascii=False, sort_keys=True))

    by_label = {str(report["label"]): report for report in reports}
    assert by_label["pure_select_evaluate"]["p95_ms"] < 1000
    assert by_label["harness_check_local_state"]["p95_ms"] < 3000
    assert by_label["phase_grant_issue_verify_redeem"]["p95_ms"] < 3000
    assert by_label["capability_ticket_issue_redeem"]["p95_ms"] < 3000
    assert by_label["cold_start_sopctl_help"]["p95_ms"] < 10000
    assert by_label["incremental_surface_scan"]["p95_ms"] < 5000
    assert by_label["harness_check_local_state"]["cost_per_sample"]["ticket_issued"] == 0.0
    assert by_label["harness_check_local_state"]["cost_per_sample"]["grant_count"] == 0.0
    assert by_label["phase_grant_issue_verify_redeem"]["cost_per_sample"]["grant_count"] == 1.0
    assert by_label["capability_ticket_issue_redeem"]["cost_per_sample"]["ticket_redeemed"] == 1.0
    return reports


def test_perf_baseline(tmp_path: Path) -> None:
    """Collect WP-G p50/p95/min/max and assert only noise-tolerant ceilings."""
    _test_perf_baseline(tmp_path)


def test_reference_host_cli_contract(tmp_path: Path) -> None:
    """Smoke-test the new CLI reference host; this is not JobsFlow evidence."""
    project = tmp_path / "reference-cli-project"
    _init_project(project)
    source = tmp_path / "source.txt"
    source.write_text("reference-host\n", encoding="utf-8")
    env = _subprocess_env()

    def run(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(PYTHON), str(HOST_CLI), "--project", str(project), *args],
            cwd=ROOT,
            env=env,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=60,
        )

    read = run("read", str(source))
    assert read.returncode == 0 and "reference-host" in read.stdout
    status = run("status")
    assert status.returncode == 0 and json.loads(status.stdout)["executed"] is True
    target = tmp_path / "written.txt"
    write = run("write", str(target), "controlled")
    assert write.returncode == 0 and target.read_text(encoding="utf-8") == "controlled"
    hook = run("hook", input_text=json.dumps({"argv": ["true"], "action": "status"}))
    assert hook.returncode == 0
    fetch = run("fetch")
    assert fetch.returncode == 0 and json.loads(fetch.stdout)["executed"] is True


def test_reference_host_worker_contract() -> None:
    """Smoke-test the new API/worker reference host seam."""
    spec = importlib.util.spec_from_file_location("reference_host_worker", HOST_WORKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    batch = module.run_batch([{"id": "a", "text": "xyz"}, {"id": "b", "text": ""}])
    assert [item["id"] for item in batch["outputs"]] == ["a", "b"]
    descriptor = module.expensive_op_descriptor()
    assert descriptor["is_expensive"] is True and descriptor["needs_admission"] is True
    calls: list[dict[str, object]] = []
    expensive = module.run_expensive(
        batch["outputs"], admit=lambda context: calls.append(context) is None
    )
    assert len(expensive["outputs"]) == 2 and calls
    narrowed = module.narrow(expensive["outputs"], lambda item: item["score"] > 0)
    assert [item["id"] for item in narrowed] == ["a"]
    assert module.business_check([{"id": "z", "score": -1}])[0]["severity"] == "blocking"
    assert module.business_check([{"id": "z", "score": 1}]) == []
    assert module.run_with_retry("abcd")["attempts"] == 2

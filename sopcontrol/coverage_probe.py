"""Harmless penetration probes that can elevate a surface to verified."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .action_plane import commit_action_result, evaluate_payload
from .coverage import record_probe_result
from .coverage_model import ProbeResult
from .context import ProjectScope


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def verify_surface(root: Path | str, surface: str) -> ProbeResult:
    """Run a no-side-effect probe for one surface through the Action Plane.

    Does not modify business source. Records probe result for the current worktree.
    """
    root = Path(root).resolve()
    scope = ProjectScope(root, mode="discovery")
    wt = scope.worktree_id

    probes = {
        "filesystem_write": {
            "tool_name": "Write",
            "tool_input": {
                "file_path": ".sopcontrol-local/coverage/probe-write.txt",
                "content": "probe",
            },
        },
        "filesystem_read": {
            "tool_name": "Read",
            "tool_input": {"file_path": "README.md"},
        },
        "shell": {
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
        },
        "search": {
            "tool_name": "Glob",
            "tool_input": {"pattern": "*.md"},
        },
        "network": {
            "tool_name": "WebFetch",
            "tool_input": {"url": "https://example.invalid/sopctl-probe"},
        },
        "browser": {
            "tool_name": "browser_navigate",
            "tool_input": {"url": "about:blank"},
        },
        "git_hooks": None,  # structural — verified only if hook file exists + marker
        "harness_claude": None,
        "harness_opencode": None,
        "harness_codex": None,
    }

    if surface not in probes and not surface.startswith("unknown:"):
        result = ProbeResult(
            surface=surface,
            passed=False,
            evidence_digest=_digest(f"unsupported:{surface}"),
            detail="no_probe_defined",
            worktree_id=wt,
        )
        record_probe_result(root, result)
        return result

    # Structural adapter probes (no tool call)
    if probes.get(surface) is None and surface in {
        "git_hooks", "harness_claude", "harness_opencode", "harness_codex",
    }:
        from .attachment import attachment_status

        status = attachment_status(root)
        if surface == "git_hooks":
            passed = status.git_hook in {"sopctl", "chained"}
            detail = f"git_hook={status.git_hook}"
        elif surface == "harness_claude":
            passed = status.harness.get("claude") == "installed"
            detail = f"claude={status.harness.get('claude')}"
        elif surface == "harness_opencode":
            passed = status.harness.get("opencode") == "installed"
            detail = f"opencode={status.harness.get('opencode')}"
        else:
            # Codex has no live pre-tool hook — structural probe cannot claim verified
            passed = False
            detail = "codex_projection_only_no_pretool"
        result = ProbeResult(
            surface=surface,
            passed=passed,
            evidence_digest=_digest(detail),
            detail=detail,
            worktree_id=wt,
        )
        record_probe_result(root, result)
        return result

    payload = probes[surface]
    assert payload is not None
    decision = evaluate_payload(payload, harness="probe")
    # Probe passes if Action Plane returned a decision (observe/allow/deny/ask)
    # without crashing — proves the surface is on the call path.
    passed = decision.decision in {"observe", "allow", "deny", "ask"}
    # High-impact write to .sopcontrol-local should be allow (not controller dir)
    if surface == "filesystem_write":
        passed = decision.decision == "allow"
    try:
        commit_action_result(root, decision)
    except Exception:
        pass
    result = ProbeResult(
        surface=surface,
        passed=passed,
        evidence_digest=(
            decision.envelope.raw_event_digest if decision.envelope else _digest(surface)
        ),
        detail=f"decision={decision.decision}",
        worktree_id=wt,
    )
    record_probe_result(root, result)
    return result

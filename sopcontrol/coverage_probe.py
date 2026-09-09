"""Harmless penetration probes that can elevate a surface to verified.

Verified requires a live harness adapter (Claude PreToolUse or OpenCode plugin)
and a decision path that goes through `sopctl harness-check` — the same entry
hooks use. Pure `evaluate_payload` alone must never mint verified.
"""
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


def _live_harness_present(root: Path) -> tuple[bool, str]:
    from .attachment import attachment_status

    status = attachment_status(root)
    if status.harness.get("claude") == "installed":
        return True, "claude"
    if status.harness.get("opencode") == "installed":
        return True, "opencode"
    return False, "none"


def _run_via_harness_check(root: Path, payload: dict) -> tuple[bool, str, dict]:
    """Invoke the same CLI path PreToolUse / OpenCode plugins call."""
    from .cli import main
    import io
    from contextlib import redirect_stdout, redirect_stderr

    raw = json.dumps(payload, ensure_ascii=False)
    buf = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        rc = main(["harness-check", str(root), "--payload", raw])
    out = buf.getvalue().strip()
    # Parse last JSON object line from stdout
    decision_payload: dict = {}
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                decision_payload = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    ok = rc == 0 and bool(decision_payload)
    detail = f"harness-check rc={rc}"
    return ok, detail, decision_payload


def verify_surface(root: Path | str, surface: str) -> ProbeResult:
    """Run a no-side-effect probe for one surface.

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
        "git_hooks": None,
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

    # Structural adapter probes (presence only — never verified for codex pre-tool)
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

    # Tool-surface probes require a live harness adapter + harness-check path
    live, harness_name = _live_harness_present(root)
    if not live:
        result = ProbeResult(
            surface=surface,
            passed=False,
            evidence_digest=_digest("no_live_harness"),
            detail="no_live_harness_adapter",
            worktree_id=wt,
        )
        record_probe_result(root, result)
        return result

    payload = probes[surface]
    assert payload is not None
    ok, detail, decision_payload = _run_via_harness_check(root, payload)
    perm = ""
    if decision_payload:
        perm = str(
            (decision_payload.get("hookSpecificOutput") or {}).get("permissionDecision")
            or ""
        )
    passed = ok and perm in {"allow", "ask", "deny"}
    # Write probe must be allow (path is under .sopcontrol-local, not controller)
    if surface == "filesystem_write":
        passed = ok and perm == "allow"

    # Also record Action Plane receipt for ledger correlation
    try:
        decision = evaluate_payload(payload, harness=harness_name)
        commit_action_result(root, decision)
    except Exception:
        pass

    result = ProbeResult(
        surface=surface,
        passed=passed,
        evidence_digest=_digest(f"{harness_name}:{surface}:{perm}:{detail}"),
        detail=f"via=harness-check harness={harness_name} {detail} perm={perm or '-'}",
        worktree_id=wt,
    )
    record_probe_result(root, result)
    return result

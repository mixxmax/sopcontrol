"""CLI — sopctl attach / attach-status / detach --plan (Phase A)."""
from __future__ import annotations

import json
import sys

from .attachment import (
    apply_attachment,
    attachment_status,
    format_plan,
    format_report,
    plan_attachment,
    plan_detachment,
)
from .cli_common import _project


def cmd_attach(args) -> int:
    root = _project(args.path)
    mode = "observe" if getattr(args, "mode", None) == "observe" else "auto"
    plan_only = bool(getattr(args, "plan", False))
    as_json = bool(getattr(args, "json", False))

    plan = plan_attachment(root, requested_mode=mode)
    if plan_only:
        if as_json:
            print(json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2))
        else:
            print(format_plan(plan))
        return 0

    report = apply_attachment(plan)
    if as_json:
        print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print(format_report(report))
    if report.connection_state in {"connected", "connected_with_gaps"}:
        return 0
    return 1


def cmd_attach_status(args) -> int:
    root = _project(args.path)
    status = attachment_status(root)
    if getattr(args, "json", False):
        print(json.dumps(status.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print(f"root: {status.root}")
        print(f"connected: {status.connected}")
        print(f"project_id: {status.project_id or '-'}")
        print(f"control_dir: {status.has_control_dir}  identity: {status.has_identity}  registry: {status.has_registry}")
        print(f"git_hook: {status.git_hook}")
        print(f"harness: {status.harness}")
        if status.last_receipt_path:
            print(f"last_receipt: {status.last_receipt_path}")
        if status.gaps:
            print("gaps: " + ", ".join(status.gaps))
    return 0 if status.connected else 1


def cmd_detach(args) -> int:
    root = _project(args.path)
    if not getattr(args, "plan", False):
        print(
            "detach 需要 --plan（Phase A 仅预览）。真正解除需后续显式确认命令。",
            file=sys.stderr,
        )
        return 2
    preview = plan_detachment(root)
    if getattr(args, "json", False):
        print(json.dumps(preview.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print(f"Detach preview for {preview.root}")
        print("removable (sopctl-owned):")
        for item in preview.removable:
            print(f"  - {item.path}: {item.summary}")
        print("keep:")
        for item in preview.keep:
            print(f"  - {item}")
        for note in preview.notes:
            print(f"note: {note}")
    return 0

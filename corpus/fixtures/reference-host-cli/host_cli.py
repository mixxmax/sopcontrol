"""参考宿主 CLI（非 JobsFlow 证据）。

This deliberately small host exposes the seams that a real CLI would hand to
SOP Control: a direct file read, a read-only bridge action, an admitted local
write, an external hook, and a high-impact network-shaped action whose child
must redeem the handoff ticket before the stub work is considered executed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


HOST_ID = "reference-host-cli"


def _child_argv(project: Path, command: str, *args: str) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--project",
        str(project),
        command,
        *args,
    ]


def cmd_read(args: argparse.Namespace) -> int:
    """Direct host read; the host can classify this as a low-risk operation."""
    content = Path(args.file).read_text(encoding="utf-8")
    print(content, end="" if content.endswith("\n") else "\n")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Read-only bridge action; it must not create a capability ticket."""
    from sopcontrol.bridge import run_bridge

    receipt = run_bridge(
        Path(args.project),
        integration_id=HOST_ID,
        action="status",
        argv=["true"],
    )
    print(
        json.dumps(
            {
                "executed": bool(receipt.get("executed")),
                "ticket": receipt.get("ticket"),
                "challenge_count": receipt.get("challenge_count", 0),
            },
            ensure_ascii=False,
        )
    )
    return 0 if receipt.get("executed") else 1


def _admit_write(args: argparse.Namespace) -> int:
    """Cooperating child: redeem the write handoff before touching the target."""
    from sopcontrol.bridge import admit_ticket

    ticket_file = os.environ.get("SOPCTL_TICKET_FILE", "")
    if not ticket_file:
        print("reference-host-cli write: missing SOPCTL_TICKET_FILE", file=sys.stderr)
        return 1
    project = Path(args.project)
    child_argv = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
    admit_ticket(
        project,
        ticket_file=ticket_file,
        integration_id=HOST_ID,
        action="host-cli.write",
        argv=child_argv,
        side_effect="external_write",
    )
    target = Path(args.file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(args.text, encoding="utf-8")
    print(json.dumps({"admitted": True, "written": str(target)}, ensure_ascii=False))
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    """Controlled local write: the child must redeem before the write occurs."""
    from sopcontrol.bridge import run_bridge

    project = Path(args.project)
    receipt = run_bridge(
        project,
        integration_id=HOST_ID,
        action="host-cli.write",
        argv=_child_argv(project, "_admit-write", args.file, args.text),
        side_effect="external_write",
    )
    print(
        json.dumps(
            {
                "executed": bool(receipt.get("executed")),
                "ticket": receipt.get("ticket"),
                "redemption_point": receipt.get("redemption_point"),
                "written": str(args.file),
            },
            ensure_ascii=False,
        )
    )
    return 0 if receipt.get("executed") else 1


def cmd_hook(args: argparse.Namespace) -> int:
    """External hook adapter: stdin JSON is sent through the bridge."""
    from sopcontrol.bridge import run_bridge

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        print("reference-host-cli hook: invalid JSON", file=sys.stderr)
        return 1
    argv = [str(item) for item in payload.get("argv", ["true"])]
    action = str(payload.get("action", "status"))
    receipt = run_bridge(
        Path(args.project),
        integration_id=HOST_ID + ".hook",
        action=action,
        argv=argv,
    )
    return 0 if receipt.get("executed") else 1


def _admit_fetch(args: argparse.Namespace) -> int:
    """Cooperating child for the network-shaped high-impact stub."""
    from sopcontrol.bridge import admit_ticket

    ticket_file = os.environ.get("SOPCTL_TICKET_FILE", "")
    if not ticket_file:
        print("reference-host-cli fetch: missing SOPCTL_TICKET_FILE", file=sys.stderr)
        return 1
    project = Path(args.project)
    child_argv = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
    admit_ticket(
        project,
        ticket_file=ticket_file,
        integration_id=HOST_ID + ".fetch",
        action="host-cli.fetch",
        argv=child_argv,
        side_effect="network_request",
    )
    # No network request is made.  This is only an adapter seam fixture.
    print(json.dumps({"admitted": True, "stub": "network-shaped"}, ensure_ascii=False))
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    """High-impact stand-in: external side effect requires ticket admission."""
    from sopcontrol.bridge import run_bridge

    project = Path(args.project)
    receipt = run_bridge(
        project,
        integration_id=HOST_ID + ".fetch",
        action="host-cli.fetch",
        argv=_child_argv(project, "_admit-fetch"),
        side_effect="network_request",
    )
    print(
        json.dumps(
            {
                "executed": bool(receipt.get("executed")),
                "ticket": receipt.get("ticket"),
                "redemption_point": receipt.get("redemption_point"),
                "stub": "network-shaped",
            },
            ensure_ascii=False,
        )
    )
    return 0 if receipt.get("executed") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reference-host-cli",
        description="本地参考宿主 CLI（非 JobsFlow 证据）",
    )
    parser.add_argument("--project", default=".", help="已初始化 .sopcontrol 的项目根")
    sub = parser.add_subparsers(dest="command", required=True)

    read = sub.add_parser("read", help="直接读取一个文件")
    read.add_argument("file")
    read.set_defaults(func=cmd_read)

    status = sub.add_parser("status", help="只读 bridge 动作")
    status.set_defaults(func=cmd_status)

    write = sub.add_parser("write", help="受控本地写入")
    write.add_argument("file")
    write.add_argument("text")
    write.set_defaults(func=cmd_write)

    hook = sub.add_parser("hook", help="stdin JSON 外部 hook")
    hook.set_defaults(func=cmd_hook)

    fetch = sub.add_parser("fetch", help="高影响网络形状动作")
    fetch.set_defaults(func=cmd_fetch)

    internal_write = sub.add_parser("_admit-write", help=argparse.SUPPRESS)
    internal_write.add_argument("file")
    internal_write.add_argument("text")
    internal_write.set_defaults(func=_admit_write)

    internal_fetch = sub.add_parser("_admit-fetch", help=argparse.SUPPRESS)
    internal_fetch.set_defaults(func=_admit_fetch)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

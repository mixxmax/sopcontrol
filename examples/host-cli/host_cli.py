"""WP-K 参考宿主之一：Host-CLI（非 JobsFlow 证据，仅证明 adapter 缝通用）。

结构：CLI 入口 + 文件读取 + 只读动作（bridge 无票） + 受控写（本地落盘+回执）
+ 外部 hook（stdin JSON 准入） + 高影响动作（curl 类网络项走 ticket 全周期）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HOST_ID = "host-cli"


def cmd_read(args) -> int:
    data = Path(args.file).read_text(encoding="utf-8")
    print(data, end="" if data.endswith("\n") else "\n")
    return 0


def cmd_status(args) -> int:
    """低风险只读动作：经 bridge，无票据。"""
    from sopcontrol.bridge import run_bridge
    receipt = run_bridge(Path(args.project), argv=["true"],
                         integration_id=HOST_ID, action="status")
    print(json.dumps({"executed": receipt.get("executed")}, ensure_ascii=False))
    return 0 if receipt.get("executed") else 1


def cmd_write(args) -> int:
    """受控写：本地文件落盘 + 回执记录（合作操作者边界内可审计）。"""
    from sopcontrol.bridge import run_bridge
    target = Path(args.file)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(args.text, encoding="utf-8")
    receipt = run_bridge(Path(args.project), argv=["true"],
                         integration_id=HOST_ID, action="status")
    print(json.dumps({"written": str(target), "bytes": len(args.text),
                      "bridge_ok": bool(receipt.get("executed"))},
                     ensure_ascii=False))
    return 0


def cmd_hook(args) -> int:
    """外部 hook：stdin 读 envelope JSON，准入则 0，否则 1。"""
    from sopcontrol.bridge import run_bridge
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        print("hook: invalid json", file=sys.stderr)
        return 1
    receipt = run_bridge(Path(args.project),
                         argv=[str(x) for x in payload.get("argv", ["true"])],
                         integration_id=HOST_ID,
                         action=str(payload.get("action", "status")))
    return 0 if receipt.get("executed") else 1


def cmd_fetch(args) -> int:
    """高影响动作：curl 类网络项必须走 ticket（签发→校验→兑换），无票拒行。"""
    from sopcontrol.tickets import (
        issue_ticket, redeem_ticket, verify_ticket_for_admission,
    )
    root = Path(args.project)
    ticket = issue_ticket(root, action="host-cli.fetch",
                          input_fingerprint="curl-version",
                          allowed_side_effects=["network_request"])
    verify_ticket_for_admission(root, ticket_id=ticket.ticket_id,
                                secret=ticket.secret, action="host-cli.fetch",
                                input_fingerprint="curl-version",
                                side_effect="network_request")
    redeem_ticket(root, ticket_id=ticket.ticket_id, secret=ticket.secret,
                  action="host-cli.fetch", input_fingerprint="curl-version",
                  side_effect="network_request")
    print(json.dumps({"fetched": True, "ticket": ticket.ticket_id},
                     ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="host-cli", description="参考宿主 CLI（非真实业务）")
    p.add_argument("--project", default=".", help="项目根（含 .sopcontrol）")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read", help="文件读取")
    r.add_argument("file")
    r.set_defaults(func=cmd_read)
    s = sub.add_parser("status", help="只读动作（bridge）")
    s.set_defaults(func=cmd_status)
    w = sub.add_parser("write", help="受控写")
    w.add_argument("file")
    w.add_argument("text")
    w.set_defaults(func=cmd_write)
    h = sub.add_parser("hook", help="外部 hook（stdin envelope）")
    h.set_defaults(func=cmd_hook)
    f = sub.add_parser("fetch", help="高影响动作（ticket 全周期）")
    f.set_defaults(func=cmd_fetch)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

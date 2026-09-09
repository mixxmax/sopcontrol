"""桥接 P0：ControlEnvelope 稳定 operation_id、挑战-重试-兑换-回执、只读免票、原子兑换。"""
from __future__ import annotations

import threading

import pytest

from sopcontrol.bridge import (
    canonical_fingerprint,
    operation_id,
    run_bridge,
)
from sopcontrol.tickets import ticket_public_view


def test_operation_id_and_fingerprint_are_stable_across_retries(tmp_path):
    """§3.1：同一逻辑操作的挑战与重试必须同 operation_id / fingerprint；
    指纹不含时间、attempt、secret、ticket id。"""
    argv = ["product", "scan", "--url", "https://example.test/api"]
    op1 = operation_id("scan.cli", "network.request", argv)
    fp1 = canonical_fingerprint("scan.cli", "network.request", argv)
    op2 = operation_id("scan.cli", "network.request", list(argv))
    fp2 = canonical_fingerprint("scan.cli", "network.request", list(argv))

    assert op1 == op2 and op1.startswith("op-")
    assert fp1 == fp2 and fp1.startswith("sha256:")
    # 任何输入变化都改变指纹
    assert canonical_fingerprint("scan.cli", "network.request", ["product", "scan", "--url", "https://other.test"]) != fp1


def test_readonly_action_runs_without_ticket(tmp_path):
    """§4.4：本地只读动作不进入票据流程，直接执行并出回执。"""
    receipt = run_bridge(tmp_path, integration_id="scan.cli", action="scan", argv=["echo", "hello"])

    assert receipt["side_effect"] == "none"
    assert receipt["ticket"] is None
    assert receipt["executed"] is True
    assert receipt["exit_code"] == 0
    assert receipt["attempt_id"] != receipt["operation_id"]
    assert "hello" in receipt["stdout_tail"]


def test_ticket_required_action_challenges_once_then_succeeds_on_retry(tmp_path):
    receipt = run_bridge(
        tmp_path,
        integration_id="scan.cli",
        action="network.scan",
        argv=["echo", "side-effect"],
        side_effect="network_request",
    )

    assert receipt["challenge_count"] == 1          # 无票第一次只产生一次挑战
    assert receipt["executed"] is True              # 自动重试后真实执行
    assert receipt["ticket"]["ticket_id"].startswith("tkt-")
    assert "secret" not in receipt["ticket"]        # 回执不含 secret
    assert receipt["operation_id"].startswith("op-")


def test_tampered_retry_is_rejected_and_ticket_not_consumed(tmp_path):
    """§4.3/§10.3：重试改变输入/动作被拒；票据未消费时正确重试仍可兑换。"""
    from sopcontrol.bridge import challenge_ticket
    from sopcontrol.tickets import redeem_ticket, TicketError

    argv = ["tool", "sync"]
    fp = canonical_fingerprint("sync.cli", "external.write", argv)
    ticket = challenge_ticket(
        tmp_path, integration_id="sync.cli", action="external.write",
        input_fingerprint=fp, side_effect="external_write",
    )

    with pytest.raises(TicketError, match="fingerprint"):
        redeem_ticket(
            tmp_path, ticket_id=ticket.ticket_id, secret=ticket.secret,
            action="external.write", input_fingerprint="sha256:tampered",
            side_effect="external_write",
        )
    # 拒绝后票据未被消费：同一指纹的正确重试仍可兑换
    redeemed = redeem_ticket(
        tmp_path, ticket_id=ticket.ticket_id, secret=ticket.secret,
        action="external.write", input_fingerprint=fp,
        side_effect="external_write",
    )
    assert redeemed.consumed_at is not None
    # 已消费后再兑：拒绝（防双消费）
    with pytest.raises(TicketError, match="consumed"):
        redeem_ticket(
            tmp_path, ticket_id=ticket.ticket_id, secret=ticket.secret,
            action="external.write", input_fingerprint=fp,
            side_effect="external_write",
        )


def test_concurrent_redemption_only_one_succeeds(tmp_path):
    """§9 P1：跨进程原子锁防止并发双消费。"""
    from sopcontrol.bridge import challenge_ticket
    from sopcontrol.tickets import redeem_ticket, TicketError

    fp = canonical_fingerprint("sync.cli", "external.write", ["tool", "sync"])
    ticket = challenge_ticket(
        tmp_path, integration_id="sync.cli", action="external.write",
        input_fingerprint=fp, side_effect="external_write",
    )
    results = []
    def redeem():
        try:
            redeem_ticket(
                tmp_path, ticket_id=ticket.ticket_id, secret=ticket.secret,
                action="external.write", input_fingerprint=fp,
                side_effect="external_write",
            )
            results.append("ok")
        except Exception:
            results.append("rejected")

    threads = [threading.Thread(target=redeem) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert results.count("ok") == 1
    assert results.count("rejected") == 7


def test_secret_never_persists_in_public_view_or_receipt(tmp_path):
    receipt = run_bridge(
        tmp_path, integration_id="scan.cli", action="network.scan",
        argv=["echo", "x"], side_effect="network_request",
    )
    blob = str({k: v for k, v in receipt.items() if k != "ticket_model"})
    secret = receipt["ticket_model"].secret
    assert receipt["ticket"].get("secret") is None
    assert secret not in blob


def test_unified_fingerprint_matches_action_envelope(tmp_path):
    """§9.5：bridge 动作并入 ActionEnvelope 分类机器——同一命令经任意
    harness 到达，指纹一致（build_envelope 与 canonical 同基）。"""
    from sopcontrol.action_plane import build_envelope

    argv = ["product", "scan", "--url", "https://example.test/api"]
    command = " ".join(argv)
    envelope = build_envelope(
        {"tool_name": "Bash", "tool_input": {"command": command}},
        harness="bridge",
        task_id="scan.cli",
    )
    basis = {
        "surface": envelope.surface,
        "operation": envelope.operation,
        "target": envelope.target,
        "integration_id": "scan.cli",
        "action": "network.scan",
    }
    import json as _json
    import hashlib as _hashlib
    expected = "sha256:" + _hashlib.sha256(
        _json.dumps(basis, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    assert canonical_fingerprint("scan.cli", "network.scan", argv) == expected
    # 同一逻辑动作重试不变
    assert canonical_fingerprint("scan.cli", "network.scan", list(argv)) == expected


def test_bridge_install_and_remove_wrapper_roundtrip(tmp_path):
    """§9.4：launcher 生成可执行、remove 回滚移除；回滚清单记录 existed_before。"""
    from sopcontrol.bridge import install_wrapper, remove_wrapper

    installed = install_wrapper(
        tmp_path, integration_id="scan.cli",
        command=["/Users/xiezhijie/sopcontrol/.venv/bin/sopctl", "bridge", "run",
                 "--action", "network.scan", "--side-effect", "network_request"],
        name="product-scan",
    )
    launcher = tmp_path / ".sopcontrol-local" / "bin" / "product-scan"
    assert launcher.exists() and launcher.stat().st_mode & 0o111

    removed = remove_wrapper(tmp_path, name="product-scan")
    assert removed["removed"] is True
    assert not launcher.exists()
    # 幂等：再 remove 报 removed=False
    assert remove_wrapper(tmp_path, name="product-scan")["removed"] is False

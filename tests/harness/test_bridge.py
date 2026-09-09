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

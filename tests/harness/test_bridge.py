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
        argv=["curl", "--version"],
        side_effect="network_request",
    )

    assert receipt["challenge_count"] == 1          # 无票第一次只产生一次挑战
    assert receipt["executed"] is True              # 自动重试后真实执行
    assert receipt["ticket"]["ticket_id"].startswith("tkt-")
    assert "secret" not in receipt["ticket"]        # 回执不含 secret
    assert receipt["operation_id"].startswith("op-")
    assert receipt["redemption_point"].startswith("bridge ")


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
        argv=["curl", "--version"], side_effect="network_request",
    )

    def _walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert k != "secret", "secret key leaked into receipt object"
                yield from _walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from _walk(v)

    assert "ticket_model" not in receipt  # 对象级剥离：打印过滤之外无残留
    list(_walk(receipt))
    assert receipt["ticket"].get("secret") is None
    # handoff 文件跑后删除，不留 secret 载体
    from pathlib import Path as _Path

    assert receipt["ticket_handoff"].endswith("(removed after run)")
    assert not _Path(receipt["ticket_handoff"].split(" ")[0]).exists()


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


def test_undeclared_side_effect_mismatch_or_unknown_refused(tmp_path):
    # 声明 database_write 实跑 curl：可证伪的矛盾 → 拒绝
    r1 = run_bridge(tmp_path, integration_id="scan.cli", action="network.scan",
                    argv=["curl", "--version"], side_effect="database_write")
    assert r1["executed"] is False and "不符" in r1["error"]
    # 未知副作用字符串：拒绝
    r2 = run_bridge(tmp_path, integration_id="scan.cli", action="network.scan",
                    argv=["echo", "x"], side_effect="teleport")
    assert r2["executed"] is False
    # 只读动作未声明但触及 curl：自动进票据流程（fail-closed 分类生效）
    r3 = run_bridge(tmp_path, integration_id="scan.cli", action="scan",
                    argv=["curl", "--version"])
    assert r3["executed"] is True and r3["challenge_count"] == 1
    assert r3["side_effect"] == "network_request"


def test_identifier_traversal_rejected_and_preexisting_restored(tmp_path):
    import pytest as _pytest

    from sopcontrol.bridge import install_wrapper, remove_wrapper

    with _pytest.raises(ValueError):
        install_wrapper(tmp_path, integration_id="x", command=["echo"], name="../../escaped")
    with _pytest.raises(ValueError):
        remove_wrapper(tmp_path, name="../../escaped")
    assert not (tmp_path / "escaped").exists()

    launcher = tmp_path / ".sopcontrol-local" / "bin" / "keep-me"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/bin/sh\necho ORIGINAL\n", encoding="utf-8")
    install_wrapper(tmp_path, integration_id="x", command=["echo", "new"], name="keep-me")
    assert "ORIGINAL" not in launcher.read_text(encoding="utf-8")
    removed = remove_wrapper(tmp_path, name="keep-me")
    assert removed["restored"] is True and removed["removed"] is False
    assert "ORIGINAL" in launcher.read_text(encoding="utf-8")


def test_admission_verification_for_handoff_ticket(tmp_path):
    from sopcontrol.tickets import TicketError, issue_ticket, verify_ticket_for_admission

    t = issue_ticket(tmp_path, action="network.scan", input_fingerprint="fp-9",
                     allowed_side_effects=["network_request"])
    ok = verify_ticket_for_admission(
        tmp_path, ticket_id=t.ticket_id, secret=t.secret,
        action="network.scan", input_fingerprint="fp-9",
        side_effect="network_request")
    assert ok["verified"] is True
    import pytest as _pytest

    with _pytest.raises(TicketError):
        verify_ticket_for_admission(
            tmp_path, ticket_id=t.ticket_id, secret="wrong",
            action="network.scan", input_fingerprint="fp-9")

"""§8.5 必须添加的反例测试（Batch 3: Capability Ticket 与低成本授权）。"""
from __future__ import annotations

import pytest

from sopcontrol.bridge import challenge_admission, run_bridge
from sopcontrol.tickets import (
    TicketError,
    _load_ticket,
    _ticket_dir,
    _validate_ticket,
    issue_ticket,
    redeem_ticket,
    utcnow,
    verify_ticket_for_admission,
)


def test_expected_plan_rejects_empty_ticket_plan(tmp_path):
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
        effective_plan_digest="",
    )
    with pytest.raises(TicketError, match="plan digest"):
        redeem_ticket(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
            expected_plan_digest="plan-expected",
        )
    with pytest.raises(TicketError, match="plan digest"):
        verify_ticket_for_admission(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
            expected_plan_digest="plan-expected",
        )


def test_expected_phase_rejects_empty_ticket_phase(tmp_path):
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
        phase="",
    )
    with pytest.raises(TicketError, match="phase"):
        redeem_ticket(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
            expected_phase="audit",
        )
    with pytest.raises(TicketError, match="phase"):
        verify_ticket_for_admission(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
            expected_phase="audit",
        )


def test_expected_task_rejects_empty_ticket_task(tmp_path):
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
        task_id="",
    )
    with pytest.raises(TicketError, match="task"):
        redeem_ticket(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
            task_id="TASK-1",
        )
    with pytest.raises(TicketError, match="task"):
        verify_ticket_for_admission(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
            task_id="TASK-1",
        )


def test_operation_id_is_bound_in_ticket(tmp_path):
    info = challenge_admission(
        tmp_path,
        integration_id="test.cli",
        action="network.scan",
        argv=["curl", "https://example.com"],
        side_effect="network_request",
    )
    t = _load_ticket(tmp_path, info["ticket_id"])
    assert t.operation != ""
    assert t.operation == info["operation_id"]
    assert t.run_id != ""
    assert t.run_id == info["run_id"]


def test_allowed_actions_are_enforced(tmp_path):
    t = issue_ticket(
        tmp_path,
        action="git.commit",
        input_fingerprint="fp-1",
        allowed_side_effects=["external_write"],
        allowed_actions=["git.commit"],
    )
    ok = redeem_ticket(
        tmp_path,
        ticket_id=t.ticket_id,
        secret=t.secret,
        action="git.commit",
        input_fingerprint="fp-1",
        side_effect="external_write",
    )
    assert ok.consumed_at is not None

    t2 = issue_ticket(
        tmp_path,
        action="git.commit",
        input_fingerprint="fp-2",
        allowed_side_effects=["external_write"],
        allowed_actions=["git.commit"],
    )
    with pytest.raises(TicketError, match="action not allowed"):
        redeem_ticket(
            tmp_path,
            ticket_id=t2.ticket_id,
            secret=t2.secret,
            action="git.push",
            input_fingerprint="fp-2",
            side_effect="external_write",
        )


def test_ticket_cannot_cross_phase(tmp_path):
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
        phase="audit",
    )
    with pytest.raises(TicketError, match="phase"):
        redeem_ticket(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
            expected_phase="verify",
        )


def test_consumed_ticket_cannot_be_replayed(tmp_path):
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
    )
    redeem_ticket(
        tmp_path,
        ticket_id=t.ticket_id,
        secret=t.secret,
        action="network.scan",
        input_fingerprint="fp-1",
        side_effect="network_request",
    )
    with pytest.raises(TicketError, match="consumed"):
        redeem_ticket(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
        )


def test_run_id_change_is_rejected(tmp_path):
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
        run_id="run-expected-1",
    )
    with pytest.raises(TicketError, match="run_id"):
        redeem_ticket(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
            expected_run_id="run-tampered-2",
        )


def test_plan_digest_change_is_rejected(tmp_path):
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
        effective_plan_digest="plan-A",
    )
    with pytest.raises(TicketError, match="plan digest"):
        redeem_ticket(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
            expected_plan_digest="plan-B",
        )


def test_readonly_action_has_no_ticket_roundtrip(tmp_path):
    receipt = run_bridge(
        tmp_path,
        integration_id="scan.cli",
        action="scan",
        argv=["echo", "read-only-data"],
    )
    assert receipt["executed"] is True
    assert receipt["ticket"] is None
    assert receipt["side_effect"] == "none"
    ticket_dir = tmp_path / ".sopcontrol-local" / "worktrees" / "default" / "tickets"
    if ticket_dir.exists():
        assert len(list(ticket_dir.glob("*.json"))) == 0


def test_challenge_failure_does_not_issue_unbounded_tickets(tmp_path):
    receipt = run_bridge(
        tmp_path,
        integration_id="scan.cli",
        action="network.scan",
        argv=["false"],
        side_effect="network_request",
    )
    assert receipt["executed"] is False
    assert receipt["challenge_count"] <= 2
    ticket_dir = tmp_path / ".sopcontrol-local" / "worktrees" / "default" / "tickets"
    if ticket_dir.exists():
        assert len(list(ticket_dir.glob("tkt-*.json"))) <= 2


def test_ticket_not_found_raises_ticket_error(tmp_path):
    with pytest.raises(TicketError, match="ticket not found"):
        _load_ticket(tmp_path, "tkt-nonexistent", worktree_id="default")


def test_ticket_corrupt_json_raises_ticket_error(tmp_path):
    tdir = _ticket_dir(tmp_path, "default")
    tdir.mkdir(parents=True, exist_ok=True)
    bad = tdir / "tkt-bad.json"
    bad.write_text("not-json-content", encoding="utf-8")
    with pytest.raises(TicketError, match="ticket unreadable"):
        _load_ticket(tmp_path, "tkt-bad", worktree_id="default")


def test_ticket_worktree_mismatch_raises_ticket_error(tmp_path):
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
    )
    with pytest.raises(TicketError, match="ticket worktree mismatch"):
        _validate_ticket(
            t.model_copy(update={"worktree_id": "wt-1"}),
            root_path=tmp_path,
            scope_wt="wt-2",
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            when=utcnow(),
        )


def test_ticket_expected_project_id_mismatch(tmp_path):
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
    )
    with pytest.raises(TicketError, match="ticket project_id mismatch"):
        redeem_ticket(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
            expected_project_id="foreign-project",
        )


def test_ticket_expected_action_mismatch(tmp_path):
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
        allowed_actions=["network.scan"],
    )
    with pytest.raises(TicketError, match="action mismatch"):
        redeem_ticket(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
            expected_action="different.action",
        )


def test_ticket_expected_input_fingerprint_mismatch(tmp_path):
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
    )
    with pytest.raises(TicketError, match="ticket input fingerprint mismatch"):
        redeem_ticket(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
            expected_input_fingerprint="fp-expected-diff",
        )


def test_ticket_unallowed_side_effect_is_rejected(tmp_path):
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
    )
    with pytest.raises(TicketError, match="side effect not allowed"):
        redeem_ticket(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="external_write",
        )


def test_ticket_expected_capability_binding_mismatch(tmp_path):
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
        capability_binding="binding-A",
    )
    with pytest.raises(TicketError, match="ticket capability binding mismatch"):
        redeem_ticket(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
            expected_capability_binding="binding-B",
        )


def test_ticket_boundary_expiration_fails_closed(tmp_path):
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
    )
    # 边界时间：when == ticket.expires_at 必须判为已过期（严格 fail-closed，非 > 才过期）
    with pytest.raises(TicketError, match="ticket expired"):
        redeem_ticket(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
            now=t.expires_at,
        )
    with pytest.raises(TicketError, match="ticket expired"):
        verify_ticket_for_admission(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
            now=t.expires_at,
        )


def test_verify_ticket_for_admission_rejects_consumed_by_default(tmp_path):
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
    )
    # 兑换消费票据
    redeemed = redeem_ticket(
        tmp_path,
        ticket_id=t.ticket_id,
        secret=t.secret,
        action="network.scan",
        input_fingerprint="fp-1",
        side_effect="network_request",
    )
    assert redeemed.consumed_at is not None

    # verify_ticket_for_admission 没有任何绕过参数：已消费票据无条件拒绝准入
    with pytest.raises(TicketError, match="ticket already consumed"):
        verify_ticket_for_admission(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
        )


def test_verify_ticket_for_admission_is_readonly_and_never_consumes(tmp_path):
    # 正向：verify 只读核验通过，且票据之后仍可被 admit 兑换（verify 不消费）
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
    )
    info = verify_ticket_for_admission(
        tmp_path,
        ticket_id=t.ticket_id,
        secret=t.secret,
        action="network.scan",
        input_fingerprint="fp-1",
        side_effect="network_request",
    )
    assert info["verified"] is True
    assert info["consumed"] is False
    redeemed = redeem_ticket(
        tmp_path,
        ticket_id=t.ticket_id,
        secret=t.secret,
        action="network.scan",
        input_fingerprint="fp-1",
        side_effect="network_request",
    )
    assert redeemed.consumed_at is not None
    # 消费后再次 verify：拒绝（不存在 allow_consumed 旁路）
    with pytest.raises(TicketError, match="ticket already consumed"):
        verify_ticket_for_admission(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="network.scan",
            input_fingerprint="fp-1",
            side_effect="network_request",
        )


def test_phase_grant_without_allowed_actions_rejects_arbitrary_action(tmp_path):
    # 阶段授权但未声明 allowed_actions 时，不能被滥用于任意 action
    t = issue_ticket(
        tmp_path,
        action="network.scan",
        input_fingerprint="fp-1",
        allowed_side_effects=["network_request"],
        phase="audit",
        allowed_actions=[],
    )
    with pytest.raises(TicketError, match="ticket action mismatch"):
        redeem_ticket(
            tmp_path,
            ticket_id=t.ticket_id,
            secret=t.secret,
            action="arbitrary.exec",
            input_fingerprint="fp-1",
            side_effect="network_request",
        )


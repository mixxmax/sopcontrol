"""第三批：真实事件只能收紧能力，成功只产生建议，不自动升权。"""
from __future__ import annotations

from datetime import timedelta

import yaml

from sopcontrol.capability import (
    APPROVAL_TTL,
    FIXTURES,
    apply_behavior_ceiling,
    approve_profile,
    build_profile,
    control_knobs,
    effective_control_knobs,
    save_profile,
)
from sopcontrol.capability_events import (
    BEHAVIOR_WINDOW,
    BehaviorProfile,
    CapabilityEvent,
    append_capability_event,
    derive_behavior_profile,
)
from sopcontrol.cli import main
from sopcontrol.model import utcnow


def _event(kind, subject, outcome, *, model="", tier="unknown", detail=None, at=None):
    return CapabilityEvent(
        kind=kind,
        subject=subject,
        outcome=outcome,
        model=model,
        tier=tier,
        detail=detail or {},
        observed_at=at or utcnow(),
    )


def _task_events(model: str, task_id: str, *, outcome: str, action: str, to_status: str = ""):
    return [
        _event("task.open", task_id, "created", model=model, tier="unknown"),
        _event(
            "task.transition",
            task_id,
            outcome,
            detail={"action": action, "from_status": "executing", "to_status": to_status},
        ),
    ]


def _approved_live_profile(tmp_path, model="model-a", tier_fixture="strong"):
    profile = build_profile(
        model,
        FIXTURES[tier_fixture],
        source="live:opencode",
        at="t",
    )
    save_profile(tmp_path, profile)
    return approve_profile(tmp_path, expected_evaluation_id=profile.evaluation_id)


def test_derivation_is_deterministic_and_model_isolated():
    events = []
    events += _task_events("model-a", "TASK-A", outcome="denied", action="submit")
    events += _task_events("model-b", "TASK-B", outcome="allowed", action="deliver", to_status="delivered")

    a = derive_behavior_profile(events, model="model-a", now=utcnow())
    b = derive_behavior_profile(list(reversed(events)), model="model-b", now=utcnow())

    assert a.model == "model-a"
    assert a.enforced_ceiling == "weak"
    assert a.denied_transitions == 1
    assert b.model == "model-b"
    assert b.enforced_ceiling is None
    assert b.successful_deliveries == 1
    assert set(a.event_ids).isdisjoint(b.event_ids)


def test_high_risk_failure_tightens_but_success_never_auto_escalates(tmp_path):
    approved = _approved_live_profile(tmp_path)
    assert effective_control_knobs(approved, current_model="model-a").tier == "strong"

    failures = _task_events("model-a", "TASK-FAIL", outcome="denied", action="submit")
    behavior = derive_behavior_profile(failures, model="model-a", now=utcnow())
    assert apply_behavior_ceiling(control_knobs("strong"), behavior).tier == "weak"

    successes = []
    for index in range(5):
        successes += _task_events(
            "model-a", f"TASK-S{index}", outcome="allowed", action="deliver", to_status="delivered"
        )
    recommendation = derive_behavior_profile(successes, model="model-a", now=utcnow())
    assert recommendation.recommended_tier == "strong"
    assert recommendation.enforced_ceiling is None
    assert apply_behavior_ceiling(control_knobs("unknown"), recommendation).tier == "unknown"
    assert apply_behavior_ceiling(control_knobs("fragile"), recommendation).tier == "fragile"


def test_stale_events_do_not_tighten_current_profile():
    old = utcnow() - BEHAVIOR_WINDOW - timedelta(seconds=1)
    events = _task_events("model-a", "TASK-OLD", outcome="denied", action="submit")
    events = [event.model_copy(update={"observed_at": old}) for event in events]

    behavior = derive_behavior_profile(events, model="model-a", now=utcnow())
    assert behavior.event_ids == []
    assert behavior.enforced_ceiling is None


def test_live_approval_expires_to_unknown(tmp_path):
    approved = _approved_live_profile(tmp_path)
    assert approved.approved_at is not None
    before_expiry = approved.approved_at + APPROVAL_TTL - timedelta(seconds=1)
    after_expiry = approved.approved_at + APPROVAL_TTL + timedelta(seconds=1)

    assert effective_control_knobs(approved, current_model="model-a", now=before_expiry).tier == "strong"
    assert effective_control_knobs(approved, current_model="model-a", now=after_expiry).tier == "unknown"


def test_task_open_uses_conservative_intersection(tmp_path):
    rules = tmp_path / ".sopcontrol" / "rules"
    rules.mkdir(parents=True)
    (rules / "registry.yaml").write_text(
        """rules:
- rule_id: R-1
  statement: 必须接线
  modality: MUST
  status: accepted
  scope: x
  owner: test
  risk: high
  source: {type: manual_seed, ref: test}
  consumer_markers: [x]
""",
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    _approved_live_profile(tmp_path)
    for event in _task_events("model-a", "TASK-OLD", outcome="denied", action="submit"):
        append_capability_event(tmp_path, event)

    assert main([
        "task", "open", str(tmp_path),
        "--model", "model-a",
        "--objective", "行为失败后不得沿用 strong 目录范围",
        "--allow", "src",
        "--require-rule", "R-1",
        "--require-field", "status",
    ]) == 2

    assert main([
        "task", "open", str(tmp_path),
        "--model", "model-a",
        "--objective", "收紧后精确文件仍可开任务",
        "--allow", "src/a.py",
        "--require-rule", "R-1",
        "--require-field", "status",
    ]) == 0
    task_file = next((tmp_path / ".sopcontrol" / "tasks").glob("TASK-*.yaml"))
    contract = yaml.safe_load(task_file.read_text(encoding="utf-8"))["contract"]
    assert contract["write_granularity"] == "file"
    assert contract["max_repairs"] == 1
    assert "行为事件" in contract["capability_note"]


def test_behavior_profile_itself_has_no_authority():
    recommendation = BehaviorProfile(
        model="model-a",
        successful_deliveries=99,
        recommended_tier="strong",
    )
    assert apply_behavior_ceiling(control_knobs("unknown"), recommendation).tier == "unknown"

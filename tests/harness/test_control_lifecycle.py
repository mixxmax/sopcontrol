"""动态规则 P1a：基线接受 + 修正 guard + 重检 + 影响分析（§5.4 / §7）。"""
from __future__ import annotations

import pytest

from sopcontrol.cli import main
from sopcontrol.control_lifecycle import (
    BaselineAcceptError,
    accept_baseline,
    check_baseline_accept,
    load_accept,
    profile_impact,
    recheck_required,
    rejudge_allowed,
    repair_allowed,
)
from sopcontrol.control_profile import freeze_profile, normalize_profile, save_draft
from sopcontrol.control_result import ControlResult, ResultFinding, evaluate_control_result

BASE = {
    "profile_id": "run-life",
    "scope": {"project": "current-project", "task": "TASK-7", "phase": "audit"},
    "checks": {"required": ["jd_fit"], "excluded": ["style"]},
    "baseline": {"source_ref": "jd-snap", "generation_mode": "authoritative"},
    "repair": {"max_rounds": 1},
    "budget": {"max_audit_calls": 2, "max_repair_calls": 1},
}


def _frozen(tmp_path):
    save_draft(tmp_path, normalize_profile(BASE))
    return freeze_profile(tmp_path, "run-life")


def _result(frozen, **kw):
    from datetime import datetime, timezone

    base = {
        "result_id": "r1", "task_id": "TASK-7", "profile_id": "run-life",
        "profile_revision": 1, "effective_plan_digest": frozen.digest,
        "input_digest": "in", "baseline_digest": "base",
        "checked_dimensions": ["jd_fit"], "findings": [], "rounds_used": 0,
        "producer": {"actor": "a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(kw)
    return ControlResult.model_validate(base)


def test_accept_write_once_and_mode_change_requires_new_revision(tmp_path):
    _frozen(tmp_path)
    first = accept_baseline(tmp_path, task_id="TASK-7", profile_id="run-life",
                            revision=1, source_ref="jd-snap",
                            baseline_digest="base", baseline_mode="authoritative")
    same = accept_baseline(tmp_path, task_id="TASK-7", profile_id="run-life",
                           revision=1, source_ref="jd-snap",
                           baseline_digest="base", baseline_mode="authoritative")
    assert same.accepted_at == first.accepted_at
    with pytest.raises(BaselineAcceptError):
        accept_baseline(tmp_path, task_id="TASK-7", profile_id="run-life",
                        revision=1, source_ref="jd-snap",
                        baseline_digest="base-CHANGED", baseline_mode="authoritative")
    assert load_accept(tmp_path, "TASK-7", 1).baseline_digest == "base"
    assert load_accept(tmp_path, "TASK-7", 2) is None


def test_baseline_mode_change_rejected(tmp_path):
    frozen = _frozen(tmp_path)
    accept_baseline(tmp_path, task_id="TASK-7", profile_id="run-life", revision=1,
                    source_ref="jd-snap", baseline_digest="base",
                    baseline_mode="authoritative")
    escalated = _result(frozen, result_id="r-esc", baseline_mode="verify")
    assert check_baseline_accept(tmp_path, escalated, frozen) is not None
    assert "基线模式被改变" in (check_baseline_accept(tmp_path, escalated, frozen) or "")
    missing = _result(frozen, result_id="r-miss", task_id="TASK-OTHER")
    assert "未接受基线" in (check_baseline_accept(tmp_path, missing, frozen) or "")


def test_repair_only_blocking_and_tolerated_stays(tmp_path):
    frozen = _frozen(tmp_path)
    ok, _ = repair_allowed(frozen.profile, ResultFinding(dimension="jd_fit",
                                                         severity="blocking"))
    assert ok is True
    ok, why = repair_allowed(frozen.profile, ResultFinding(dimension="jd_fit",
                                                           severity="tolerated"))
    assert ok is False and "保留" in why


def test_tolerated_rejudge_needs_explicit_change():
    assert rejudge_allowed()[0] is False
    for kw in ({"profile_changed": True}, {"baseline_changed": True},
               {"evidence_changed": True}, {"higher_rule_changed": True},
               {"prior_revoked": True}):
        assert rejudge_allowed(**kw)[0] is True


def test_recheck_decided_by_frozen_plan(tmp_path):
    frozen = _frozen(tmp_path)
    assert recheck_required(frozen.profile, ["jd_fit", "unrelated"]) == ["jd_fit"]
    assert recheck_required(frozen.profile, ["style"]) == []


def test_profile_impact_analysis(tmp_path):
    old = normalize_profile(BASE)
    new = normalize_profile({**BASE, "checks": {
        "required": ["jd_fit", "llmo"], "excluded": ["style"],
        "modes": {"jd_fit": "report_only"}}})
    impact = profile_impact(old, new)
    assert impact["added_required"] == ["llmo"]
    assert impact["mode_changes"] == ["jd_fit", "llmo"]  # llmo 新增即 block 生效
    assert impact["must_recheck"] == ["jd_fit", "llmo"]


def test_cli_accept_and_evaluate_enforces_baseline(tmp_path, capsys):
    frozen = _frozen(tmp_path)
    res = _result(frozen, result_id="cli-r1")
    p = tmp_path / "res.json"
    p.write_text(res.model_dump_json(), encoding="utf-8")

    def run():
        rc = main(["control-result", "evaluate", "--file", str(p),
                   "--profile", "run-life", "--revision", "1",
                   "--path", str(tmp_path)])
        capsys.readouterr()
        return rc

    assert run() == 2  # 未接受基线
    assert main(["profile", "accept", "run-life", "--revision", "1",
                 "--task", "TASK-7", "--digest", "base",
                 "--path", str(tmp_path)]) == 0
    capsys.readouterr()
    assert run() == 0
    # digest 变化后旧接受失效（改基线走新 revision 的语义由 accept 写一次保证）
    res2 = _result(frozen, result_id="cli-r2", baseline_digest="base2")
    p.write_text(res2.model_dump_json(), encoding="utf-8")
    assert run() == 2


def test_repair_stops_at_stop_when(tmp_path):
    frozen = _frozen(tmp_path)
    blocking = ResultFinding(dimension="jd_fit", severity="blocking")
    ok, _ = repair_allowed(frozen.profile, blocking)
    assert ok is True
    ok, why = repair_allowed(frozen.profile, blocking, latest_outcome="pass")
    assert ok is False and "停止条件" in why


def test_accept_mode_locked_to_plan(tmp_path, capsys):
    _frozen(tmp_path)
    rc = main(["profile", "accept", "run-life", "--revision", "1",
               "--task", "TASK-7", "--digest", "base", "--mode", "verify",
               "--path", str(tmp_path)])
    assert rc == 2
    assert "不可在接受时改变" in capsys.readouterr().err
    assert main(["profile", "accept", "run-life", "--revision", "1",
                 "--task", "TASK-7", "--digest", "base",
                 "--path", str(tmp_path)]) == 0

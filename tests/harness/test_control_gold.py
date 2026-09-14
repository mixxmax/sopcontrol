"""动态规则 P2：金标准 + digest 一致性 + 跨执行器协议 + doctor 输出。"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from sopcontrol.cli import main
from sopcontrol.control_profile import (
    ProfileError,
    freeze_profile,
    list_frozen,
    normalize_profile,
    plan_digest,
    save_draft,
)
from sopcontrol.control_result import ControlResult, evaluate_control_result

FIX = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return yaml.safe_load((FIX / name).read_text(encoding="utf-8"))


def _freeze_fixture(tmp_path, name: str):
    data = _load_fixture(name)
    save_draft(tmp_path, normalize_profile(data))
    return freeze_profile(tmp_path, data["profile_id"])


def _result(frozen, rid, task="TASK-GOLD", **kw):
    base = {
        "result_id": rid, "task_id": task, "profile_id": frozen.profile_id,
        "profile_revision": frozen.revision,
        "phase": frozen.profile.scope.phase or "audit",
        "check_id": list(frozen.profile.checks.required)[0] if frozen.profile.checks.required else "jd_fit",
        "effective_plan_digest": frozen.digest,
        "input_digest": f"in-{rid}", "baseline_digest": "base",
        "checked_dimensions": list(frozen.profile.checks.required),
        "findings": [], "rounds_used": 0,
        "producer": {"actor": "agent-a", "independence": "self_check"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(kw)
    return ControlResult.model_validate(base)


def test_gold_strict_blocks_and_lenient_warns(tmp_path):
    strict = _freeze_fixture(tmp_path, "control_strict.yaml")
    blocking = _result(strict, "g1", findings=[
        {"dimension": "jd_fit", "severity": "blocking", "summary": "事实错误"}])
    assert evaluate_control_result(tmp_path, blocking, strict).outcome == "block"

    tmp2 = tmp_path / "lenient"
    tmp2.mkdir()
    lenient = _freeze_fixture(tmp2, "control_lenient.yaml")
    tolerated = _result(lenient, "g2", findings=[
        {"dimension": "jd_fit", "severity": "tolerated", "summary": "合理夸张"}])
    assert evaluate_control_result(tmp2, tolerated, lenient).outcome == "pass_with_warnings"


def test_gold_over_audit_reuses_without_new_call(tmp_path):
    frozen = _freeze_fixture(tmp_path, "control_lenient.yaml")
    r1 = _result(frozen, "gold-r1")
    r2 = _result(frozen, "gold-r2", input_digest="in-gold-r1")
    assert evaluate_control_result(tmp_path, r1, frozen).outcome == "pass"
    second = evaluate_control_result(tmp_path, r2, frozen)
    assert second.outcome == "pass" and any("复用" in x for x in second.reasons)


def test_plan_digest_consistent_and_tamper_rejected(tmp_path):
    frozen = _freeze_fixture(tmp_path, "control_strict.yaml")
    assert plan_digest(frozen.profile, frozen.revision) == frozen.digest
    # 同输入 profile 在别处冻结得同 digest（跨执行器一致）。
    elsewhere = tmp_path / "else"
    elsewhere.mkdir()
    save_draft(elsewhere, normalize_profile(_load_fixture("control_strict.yaml")))
    twin = freeze_profile(elsewhere, "gold-strict")
    assert twin.digest == frozen.digest
    # 篡改冻结内容 → 加载拒绝。
    p = tmp_path / ".sopcontrol-local" / "profiles" / "gold-strict.r1.json"
    import json

    data = json.loads(p.read_text(encoding="utf-8"))
    data["profile"]["checks"]["required"].append("injected")
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProfileError):
        from sopcontrol.control_profile import load_frozen

        load_frozen(tmp_path, "gold-strict", 1)


def test_cross_actor_same_plan_digest(tmp_path):
    frozen = _freeze_fixture(tmp_path, "control_lenient.yaml")
    a = _result(frozen, "x-a", findings=[
        {"dimension": "jd_fit", "severity": "blocking", "summary": "A 发现"}])
    b = _result(frozen, "x-b", input_digest="in-x-b",
                producer={"actor": "agent-b", "independence": "self_check"})
    assert b.producer.actor == "agent-b"
    assert evaluate_control_result(tmp_path, a, frozen).outcome == "block"
    assert evaluate_control_result(tmp_path, b, frozen).outcome == "pass"
    assert a.effective_plan_digest == b.effective_plan_digest == frozen.digest


def test_doctor_reports_profile_risk_cost(tmp_path, capsys, monkeypatch):
    from sopcontrol.control_lifecycle import accept_baseline

    frozen = _freeze_fixture(tmp_path, "control_strict.yaml")
    accept_baseline(tmp_path, task_id="TASK-GOLD", profile_id="gold-strict",
                    revision=1, source_ref="jd-snapshot",
                    baseline_digest="base", baseline_mode="authoritative")
    evaluate_control_result(tmp_path, _result(frozen, "d1"), frozen)
    monkeypatch.chdir(tmp_path)
    main(["doctor", str(tmp_path)])  # 空目录自诊 rc=1 不影响本断言
    out = capsys.readouterr().out
    assert "动态控制" in out and "gold-strict" in out and "审计 1 次" in out

"""LP1 刀3：legacy 重复 → delete_entry 候选；repair 目标偏向删除。"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit
from sopcontrol.candidate import CandidateStore, refresh_candidates
from sopcontrol.ledger import Ledger
from sopcontrol.metrics import structure_signals
from sopcontrol.model import Finding
from sopcontrol.repair import open_repair

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("pattern_id", ["legacy_entry_alive", "redundant_entry_point"])
def test_bypass_findings_materialize_delete_entry_candidate(tmp_path, pattern_id):
    registry = tmp_path / ".sopcontrol" / "rules" / "registry.yaml"
    registry.parent.mkdir(parents=True)
    registry.write_text("rules: []\n", encoding="utf-8")
    ledger = Ledger(tmp_path / ".sopcontrol" / "evidence" / "ledger.jsonl")
    for index in range(3):
        ledger.append_finding(Finding(
            pattern_id=pattern_id,
            rule_id="GATE-1",
            summary=f"旁路仍可达 #{index}",
            detector="test",
        ))

    result = refresh_candidates(tmp_path)
    candidates = CandidateStore(tmp_path).load()

    assert result["materialized"] == 1
    assert len(candidates) == 1
    assert candidates[0].suggested_action == "delete_entry"
    assert candidates[0].kind == "deprecation"
    assert "删除或合并" in candidates[0].statement
    assert "禁止规则" in candidates[0].statement or "登记禁止" in candidates[0].statement

def test_non_legacy_findings_still_investigate(tmp_path):
    (tmp_path / ".sopcontrol" / "rules").mkdir(parents=True)
    (tmp_path / ".sopcontrol" / "rules" / "registry.yaml").write_text(
        "rules: []\n", encoding="utf-8"
    )
    ledger = Ledger(tmp_path / ".sopcontrol" / "evidence" / "ledger.jsonl")
    for index in range(3):
        ledger.append_finding(Finding(
            pattern_id="write_only_state",
            rule_id="R-1",
            summary=f"只写 #{index}",
            detector="test",
        ))
    refresh_candidates(tmp_path)
    cand = CandidateStore(tmp_path).load()[0]
    assert cand.suggested_action == "investigate_finding"
    assert cand.kind == "finding_pattern"


@pytest.fixture()
def ci_work(tmp_path):
    w = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "ci-deploy", w)
    run_audit(w, SENSORS, DETECTORS, persist=True)
    return w


@pytest.mark.parametrize("pattern_id", ["legacy_entry_alive", "redundant_entry_point"])
def test_repair_objective_for_bypass_prefers_delete(ci_work, pattern_id):
    """注入旁路 finding 后，repair open 目标应偏向删入口。"""
    finding = Finding(
        pattern_id=pattern_id,
        rule_id="DEPLOY-001",
        summary="旧入口 deploy_direct 仍存活",
        detector="test",
    )
    Ledger(ci_work / ".sopcontrol" / "evidence" / "ledger.jsonl").append_finding(finding)

    # open_repair 会先 audit；ci-deploy 的 DEPLOY-001 通常是 gap，非 pass。
    task = open_repair(ci_work, finding.finding_id, ["scripts"], SENSORS, DETECTORS)
    assert "删除或合并旧入口" in task.contract.objective
    assert "不要再接线守卫" in task.contract.objective

def test_structure_signals_counts_delete_entry_candidates(tmp_path):
    (tmp_path / ".sopcontrol" / "rules").mkdir(parents=True)
    (tmp_path / ".sopcontrol" / "rules" / "registry.yaml").write_text(
        "rules: []\n", encoding="utf-8"
    )
    ledger = Ledger(tmp_path / ".sopcontrol" / "evidence" / "ledger.jsonl")
    for index in range(3):
        ledger.append_finding(Finding(
            pattern_id="legacy_entry_alive",
            rule_id="GATE-1",
            summary=f"旧入口 #{index}",
            detector="test",
        ))
    refresh_candidates(tmp_path)

    signals = structure_signals(tmp_path, sensors=[], detectors=[])
    assert signals["delete_entry_candidates_observed"] == 1
    assert signals["delete_entry_candidates_triaged"] == 0

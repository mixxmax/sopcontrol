"""B3 有界修复测试：契约生成、重复开单拒绝、同指纹熔断、已达标拒绝。"""
import shutil
from pathlib import Path

import pytest

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit, run_task_verify
from sopcontrol.ledger import Ledger
from sopcontrol.model import Finding
from sopcontrol.repair import RepairError, open_repair
from sopcontrol.task import TaskStore, evaluate_transition

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def work(tmp_path):
    w = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "ci-deploy", w)
    run_audit(w, SENSORS, DETECTORS, persist=True)
    return w


def gap_finding(work) -> Finding:
    findings = Ledger(work / ".sopcontrol" / "evidence" / "ledger.jsonl").load_findings()
    return next(f for f in findings if f.rule_id == "DEPLOY-001")


def test_open_repair_creates_fingerprinted_task(work):
    finding = gap_finding(work)
    task = open_repair(work, finding.finding_id, ["scripts"], SENSORS, DETECTORS)
    assert task.contract.repairs_fingerprint == finding.fingerprint
    assert task.contract.required_rules == ["DEPLOY-001"]
    assert "documented_rule_no_consumer" in task.contract.objective


def test_duplicate_active_repair_is_refused(work):
    finding = gap_finding(work)
    open_repair(work, finding.finding_id, ["scripts"], SENSORS, DETECTORS)
    with pytest.raises(RepairError, match="进行中"):
        open_repair(work, finding.finding_id, ["scripts"], SENSORS, DETECTORS)


def test_same_fingerprint_circuit_breaker(work):
    finding = gap_finding(work)
    store = TaskStore(work)
    task = open_repair(work, finding.finding_id, ["scripts"], SENSORS, DETECTORS)
    task.contract.max_repairs = 1  # 缩短预算，快速走到熔断终态
    task.revision += 1            # 外部修改同样遵守 revision 写协议
    store.save(task)

    known = {"DEPLOY-001", "ROLLBACK-001", "DEPLOY-002", "RELEASE-001"}
    for _ in range(2):  # 两轮 submit→verify 都不真正修复 → failed_unverified
        decision = evaluate_transition(task, "accept", known_rule_ids=known)
        task = store.apply(task, decision, "accept")
        decision = evaluate_transition(task, "submit", changed_paths=["scripts/deploy.py"])
        task = store.apply(task, decision, "submit", changed_paths=["scripts/deploy.py"])
        decision = run_task_verify(work, SENSORS, DETECTORS, task)
        task = store.apply(task, decision, "verify")
    assert task.status.value == "failed_unverified"

    with pytest.raises(RepairError, match="熔断"):
        open_repair(work, finding.finding_id, ["scripts"], SENSORS, DETECTORS)


def test_rule_already_passing_needs_no_repair(work):
    ledger = Ledger(work / ".sopcontrol" / "evidence" / "ledger.jsonl")
    ledger.append_finding(
        Finding(pattern_id="documented_rule_untested", rule_id="ROLLBACK-001",
                summary="构造：本已 pass 的规则出现 finding", severity="gap", detector="test")
    )
    with pytest.raises(RepairError, match="无需修复"):
        open_repair(work, ledger.load_findings()[-1].finding_id, ["scripts"], SENSORS, DETECTORS)


def test_unknown_finding_is_actionable(work):
    with pytest.raises(RepairError, match="sopctl audit"):
        open_repair(work, "fn-does-not-exist", ["scripts"], SENSORS, DETECTORS)

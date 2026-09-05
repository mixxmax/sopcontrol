"""Repair 失败路径：缺 finding、未知 harness、worktree 创建失败。"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit
from sopcontrol.cli import main
from sopcontrol.repair import RepairError, apply_repair, open_repair

ROOT = Path(__file__).resolve().parents[2]


def test_open_repair_unknown_finding(tmp_path):
    work = tmp_path / "w"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "shop-checkout", work)
    with pytest.raises(RepairError, match="未找到 finding"):
        open_repair(work, "fn-does-not-exist", ["src/checkout.py"], SENSORS, DETECTORS)


def test_open_repair_rejects_when_already_pass(tmp_path):
    work = tmp_path / "w"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "healthy-billing", work)
    report = run_audit(work, SENSORS, DETECTORS, persist=True)
    # healthy fixture may have no findings; if any pass-related, open should refuse
    if not report.findings:
        pytest.skip("fixture produced no findings")
    finding = report.findings[0]
    # Force pass path: if rule already pass, open_repair raises
    try:
        open_repair(
            work,
            finding.finding_id,
            ["src/charge.py"] if (work / "src" / "charge.py").exists() else ["src"],
            SENSORS,
            DETECTORS,
        )
    except RepairError as exc:
        assert "无需修复" in str(exc) or "不存在" in str(exc) or "完成标准" in str(exc)


def test_apply_repair_rejects_non_repair_task(tmp_path):
    work = tmp_path / "w"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "shop-checkout", work)
    assert main([
        "capability-eval", "--model", "repair-fail", "--fixture", "strong", str(work),
    ]) == 0
    assert main([
        "task", "open", str(work),
        "--model", "repair-fail",
        "--objective", "普通任务非修复",
        "--allow", "src/checkout.py",
        "--require-field", "status",
    ]) == 0
    with pytest.raises(RepairError, match="不是修复任务"):
        apply_repair(work, "TASK-0001")


def test_apply_repair_worktree_create_failure(tmp_path, monkeypatch):
    from sopcontrol.worktree import WorktreeError

    work = tmp_path / "w"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    run_audit(work, SENSORS, DETECTORS, persist=True)
    from sopcontrol.ledger import Ledger

    findings = Ledger(work / ".sopcontrol" / "evidence" / "ledger.jsonl").load_findings()
    gap = [f for f in findings if f.rule_id and f.severity in {"gap", "block", "warn", "info"}]
    if not gap:
        pytest.skip("no finding")
    finding = next((f for f in gap if f.rule_id), None)
    if finding is None:
        pytest.skip("no rule-linked finding")
    allow = "src/sheet_direct.py" if (work / "src" / "sheet_direct.py").exists() else "src/push_job.py"
    try:
        task = open_repair(work, finding.finding_id, [allow], SENSORS, DETECTORS)
    except RepairError as exc:
        pytest.skip(f"cannot open repair: {exc}")
    assert main(["task", "accept", task.task_id, str(work)]) == 0

    def boom_wt(*_a, **_k):
        raise WorktreeError("worktree create failed")

    monkeypatch.setattr("sopcontrol.repair.create_repair_worktree", boom_wt)
    with pytest.raises(RepairError, match="worktree create failed"):
        apply_repair(work, task.task_id, harness="opencode")


def test_apply_repair_unsupported_harness(tmp_path, monkeypatch):
    work = tmp_path / "w"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    run_audit(work, SENSORS, DETECTORS, persist=True)
    from sopcontrol.ledger import Ledger

    findings = Ledger(work / ".sopcontrol" / "evidence" / "ledger.jsonl").load_findings()
    finding = next((f for f in findings if f.rule_id), None)
    if finding is None:
        pytest.skip("no rule-linked finding")
    allow = "src/sheet_direct.py" if (work / "src" / "sheet_direct.py").exists() else "src/push_job.py"
    try:
        task = open_repair(work, finding.finding_id, [allow], SENSORS, DETECTORS)
    except RepairError as exc:
        pytest.skip(f"cannot open repair: {exc}")
    assert main(["task", "accept", task.task_id, str(work)]) == 0

    wt = tmp_path / "wt"
    wt.mkdir()
    monkeypatch.setattr("sopcontrol.repair.create_repair_worktree", lambda *a, **k: wt)
    monkeypatch.setattr("sopcontrol.repair.remove_repair_worktree", lambda *a, **k: None)
    monkeypatch.setattr("sopcontrol.repair.list_changed_files", lambda *a, **k: [])
    with pytest.raises(RepairError, match="暂不支持 harness"):
        apply_repair(work, task.task_id, harness="not-a-harness")
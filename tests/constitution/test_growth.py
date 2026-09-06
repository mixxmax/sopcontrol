"""无感生长：audit 自动观察+聚合；不自动写 registry。"""
from __future__ import annotations

import shutil
from pathlib import Path

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit
from sopcontrol.candidate import CandidateStore
from sopcontrol.cli import main
from sopcontrol.growth import (
    ambient_grow,
    growth_lines,
    load_growth_observations,
    load_growth_state,
    record_structural_observations,
)
from sopcontrol.model import Finding
from sopcontrol.registry import Registry
ROOT = Path(__file__).resolve().parents[2]


def test_three_audits_materialize_delete_entry_without_manual_refresh(tmp_path):
    """用户不必 candidate refresh：persist audit 三次即可物化删入口候选。"""
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    # 清空可能存在的候选
    cand = work / ".sopcontrol" / "rules" / "candidates.yaml"
    cand.unlink(missing_ok=True)

    for _ in range(3):
        run_audit(work, SENSORS, DETECTORS, persist=True)

    state = load_growth_state(work)
    assert state.observation_count >= 3
    records = CandidateStore(work).load()
    delete = [r for r in records if r.suggested_action == "delete_entry"]
    assert delete, "无感生长应物化 delete_entry 候选，无需人手 refresh"
    assert state.candidates_delete_entry >= 1


def test_growth_lines_and_cli(tmp_path):
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    ambient_grow(work, findings=[])
    # 无 finding 也有状态文件
    assert main(["growth", "status", str(work)]) == 0
    lines = growth_lines(work)
    assert any("生长" in ln or "观察" in ln for ln in lines)


def test_ambient_does_not_write_registry(tmp_path):
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "ci-deploy", work)
    before = (work / ".sopcontrol" / "rules" / "registry.yaml").read_bytes()
    for _ in range(3):
        run_audit(work, SENSORS, DETECTORS, persist=True)
    after = (work / ".sopcontrol" / "rules" / "registry.yaml").read_bytes()
    assert before == after


def test_harness_deny_grows_without_full_audit(tmp_path):
    """三次 harness 拒绝即可生长，不必跑 audit。"""
    import json
    import time

    work = tmp_path / "work"
    (work / ".sopcontrol" / "rules").mkdir(parents=True)
    (work / ".sopcontrol" / "rules" / "registry.yaml").write_text(
        "rules: []\n", encoding="utf-8",
    )
    payload = json.dumps({
        "tool_name": "Edit",
        "tool_input": {"file_path": str(work / ".sopcontrol" / "rules" / "registry.yaml")},
    })
    for _ in range(3):
        assert main([
            "harness-check", str(work), "--payload", payload,
        ]) == 0
        time.sleep(0.01)  # 保证 occurrence 时间戳不同
    state = load_growth_state(work)
    assert state.observation_count >= 3
    records = CandidateStore(work).load()
    improve = [r for r in records if r.suggested_action == "improve_entry"]
    assert improve or state.candidates_observed >= 1


def test_gate_block_records_control_observation(tmp_path):
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    # jobflow 含 fail 规则 → gate 阻断
    rc = main(["gate", str(work)])
    assert rc == 1
    state = load_growth_state(work)
    assert state.observation_count >= 1


def test_candidate_enact_opens_bounded_delete_task(tmp_path):
    """delete_entry 候选 → enact → 有界删旁路任务；不写新规则。"""
    from sopcontrol.chronicle import load_project_events
    from sopcontrol.task import TaskStore

    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    (work / ".sopcontrol" / "rules" / "candidates.yaml").unlink(missing_ok=True)
    for _ in range(3):
        run_audit(work, SENSORS, DETECTORS, persist=True)
    delete = [
        r for r in CandidateStore(work).load()
        if r.suggested_action == "delete_entry"
    ]
    assert delete
    cand_id = delete[0].candidate_id
    before_rules = (work / ".sopcontrol" / "rules" / "registry.yaml").read_bytes()

    assert main([
        "candidate", "enact", cand_id, str(work),
        "--allow", "src/sheet_direct.py",
    ]) == 0

    after_rules = (work / ".sopcontrol" / "rules" / "registry.yaml").read_bytes()
    assert before_rules == after_rules
    tasks = TaskStore(work).list_all()
    assert any("删除或合并旧入口" in t.contract.objective for t in tasks)
    assert any(cand_id in t.contract.objective for t in tasks)
    assert CandidateStore(work).get(cand_id).status == "triaged"
    assert any(
        e.kind == "growth.enact_delete" for e in load_project_events(work).events
    )


def test_structural_observation_skips_round_with_live_legacy(tmp_path):
    """M12 直接接缝：带存活 legacy finding 的轮次不得产生清零观察。"""
    work = tmp_path / "w"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "ci-deploy", work)
    # fixture 磁盘态可能带历史 ambient 产物；重置以保证断言只针对本轮
    for rel in (
        ".sopcontrol/evidence/growth-observations.jsonl",
        ".sopcontrol/rules/candidates.yaml",
    ):
        (work / rel).unlink(missing_ok=True)
    registry = Registry(work / ".sopcontrol" / "rules" / "registry.yaml")
    live = Finding(
        pattern_id="legacy_entry_alive",
        rule_id="RELEASE-001",
        summary="旧入口仍存活",
        detector="no_consumer",
    )

    written = record_structural_observations(
        work, rules=registry.load(), findings=[live], round_id="live-round"
    )

    assert written == 0
    assert not [
        obs for obs in load_growth_observations(work)
        if obs.pattern_id == "legacy_cleared"
    ]

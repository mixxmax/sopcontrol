"""无感生长：audit 自动观察+聚合；不自动写 registry。"""
from __future__ import annotations

import shutil
from pathlib import Path

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit
from sopcontrol.candidate import CandidateStore
from sopcontrol.cli import main
from sopcontrol.growth import ambient_grow, growth_lines, load_growth_state
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

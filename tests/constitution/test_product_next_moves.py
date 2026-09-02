"""产品加固：下一刀 / deliver 打帧 / 久悬 gap 退场候选。"""
from __future__ import annotations

import shutil
from pathlib import Path

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit
from sopcontrol.candidate import (
    CANDIDATE_THRESHOLD,
    RETIRE_GAP_THRESHOLD,
    CandidateStore,
    refresh_candidates,
)
from sopcontrol.cli import main
from sopcontrol.growth import load_space_snapshots, on_task_delivered
from sopcontrol.next_moves import adoption_next_moves

ROOT = Path(__file__).resolve().parents[2]


def test_doctor_prints_next_moves(tmp_path, capsys):
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    (work / ".sopcontrol" / "rules" / "candidates.yaml").unlink(missing_ok=True)
    assert main(["doctor", str(work)]) == 0
    out = capsys.readouterr().out
    assert "下一刀" in out
    assert "sopctl" in out


def test_adoption_next_moves_prioritizes_delete_entry(tmp_path):
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    (work / ".sopcontrol" / "rules" / "candidates.yaml").unlink(missing_ok=True)
    for _ in range(CANDIDATE_THRESHOLD):
        run_audit(work, SENSORS, DETECTORS, persist=True)
    moves = adoption_next_moves(work, limit=3)
    titles = [m["title"] for m in moves]
    assert any("enact" in t or "消歧" in t for t in titles)
    assert any("enact" in m["command"] for m in moves)


def test_on_task_delivered_records_snapshot_and_diff(tmp_path):
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    # 基线帧
    from sopcontrol.growth import capture_space_snapshot

    before = capture_space_snapshot(work, source="measure", persist=True, light=False)
    # 模拟消歧：删旁路文件
    sheet = work / "src" / "sheet_direct.py"
    if sheet.exists():
        sheet.unlink()
    result = on_task_delivered(work, "TASK-TEST", objective="[enact CAND-x] 删除旁路")
    assert result["ok"] is True
    snaps = load_space_snapshots(work)
    assert len(snaps) >= 2
    assert snaps[-1].source == "deliver"
    assert snaps[-1].task_id == "TASK-TEST"
    diff = result["diff"]
    assert diff is not None
    assert diff["deltas"]["ambiguity_index"]["from"] == before.ambiguity_index
    # 删旁路后指数应下降或持平（夹具可能还有其他旁路）
    assert diff["deltas"]["ambiguity_index"]["to"] <= before.ambiguity_index


def test_deliver_cli_prints_space_frame(tmp_path, capsys):
    """复用任务全链路：deliver 后输出空间帧叙事。"""
    work = tmp_path / "proj"
    work.mkdir()
    shutil.copytree(
        ROOT / "corpus" / "fixtures" / "jobflow-preview", work, dirs_exist_ok=True,
    )
    assert main([
        "capability-eval", "--model", "deliver-space", "--fixture", "strong", str(work),
    ]) == 0
    assert main([
        "task", "open", str(work),
        "--model", "deliver-space",
        "--objective", "接线 PUSH-001",
        "--allow", "src/push_job.py", "--allow", "tests/test_push.py",
        "--require-rule", "PUSH-001", "--require-field", "status",
    ]) == 0
    assert main(["task", "accept", "TASK-0001", str(work)]) == 0
    (work / "src" / "push_job.py").write_text(
        "def require_preview(rows):\n    return rows\n\n\n"
        "def push_job(sheet, row):\n    require_preview([row])\n    sheet.append(row)\n",
        encoding="utf-8",
    )
    (work / "tests" / "test_push.py").write_text(
        "from push_job import require_preview\n\n"
        "def test_preview():\n    assert require_preview([]) == []\n",
        encoding="utf-8",
    )
    assert main([
        "task", "submit", "TASK-0001", str(work),
        "--changed", "src/push_job.py", "--changed", "tests/test_push.py",
        "--field", "status=fixed",
    ]) == 0
    assert main(["task", "verify", "TASK-0001", str(work)]) == 0
    capsys.readouterr()
    assert main(["task", "deliver", "TASK-0001", str(work)]) == 0
    out = capsys.readouterr().out
    assert "空间帧(deliver)" in out
    assert "ambiguity_index=" in out
    snaps = load_space_snapshots(work)
    assert any(s.source == "deliver" and s.task_id == "TASK-0001" for s in snaps)


def test_gap_absorb_then_retire_candidate(tmp_path):
    """缺消费者：3 轮 → improve_entry；6 轮 → 额外 retire_rule（不写 registry）。"""
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    cand_path = work / ".sopcontrol" / "rules" / "candidates.yaml"
    cand_path.unlink(missing_ok=True)
    registry_before = (work / ".sopcontrol" / "rules" / "registry.yaml").read_bytes()

    for _ in range(CANDIDATE_THRESHOLD):
        run_audit(work, SENSORS, DETECTORS, persist=True)
    records = CandidateStore(work).load()
    improve = [
        r for r in records
        if r.suggested_action == "improve_entry"
        and "缺消费者" in r.statement
    ]
    # jobflow 同时有 delete_entry；improve 来自 PUSH-001 类 no_consumer
    assert improve or any(
        r.suggested_action == "improve_entry" for r in records
    ), "缺消费者应导向 improve_entry，而非只调查"

    for _ in range(RETIRE_GAP_THRESHOLD - CANDIDATE_THRESHOLD):
        run_audit(work, SENSORS, DETECTORS, persist=True)
    refresh_candidates(work)
    records = CandidateStore(work).load()
    retire = [r for r in records if r.suggested_action == "retire_rule"]
    assert retire, "久悬 gap 应物化 retire_rule 候选"
    assert "suspend" in retire[0].statement or "deprecate" in retire[0].statement
    assert (work / ".sopcontrol" / "rules" / "registry.yaml").read_bytes() == registry_before

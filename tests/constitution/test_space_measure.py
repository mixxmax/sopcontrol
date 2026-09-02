"""空间可度量：快照与前后对照。"""
from __future__ import annotations

import shutil
from pathlib import Path

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit
from sopcontrol.cli import main
from sopcontrol.growth import (
    SpaceSnapshot,
    capture_space_snapshot,
    diff_space_snapshots,
    load_space_snapshots,
)

ROOT = Path(__file__).resolve().parents[2]


def test_measure_captures_ambiguity_on_jobflow(tmp_path):
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    (work / ".sopcontrol" / "rules" / "candidates.yaml").unlink(missing_ok=True)
    (work / ".sopcontrol" / "evidence" / "space-snapshots.jsonl").unlink(missing_ok=True)
    snap = capture_space_snapshot(work, source="measure", persist=True, light=False)
    assert snap.ambiguity_index >= 1  # PUSH-002 redundant
    assert snap.bypass_open >= 1
    assert snap.snapshot_id.startswith("ss-")
    loaded = load_space_snapshots(work)
    assert len(loaded) >= 1
    assert loaded[-1].ambiguity_index == snap.ambiguity_index


def test_diff_detects_narrowing():
    older = SpaceSnapshot(
        source="measure",
        bypass_open=2,
        parallel_state=1,
        pending_delete_entry=1,
        observations=3,
    )
    newer = SpaceSnapshot(
        source="measure",
        bypass_open=0,
        parallel_state=1,
        pending_delete_entry=0,
        observations=6,
    )
    report = diff_space_snapshots(older, newer)
    assert report["verdict"] == "narrowed"
    assert report["deltas"]["ambiguity_index"]["delta"] == -2
    assert report["deltas"]["bypass_open"]["delta"] == -2


def test_diff_detects_widening():
    older = SpaceSnapshot(source="t", bypass_open=0, parallel_state=0)
    newer = SpaceSnapshot(source="t", bypass_open=2, parallel_state=0)
    assert diff_space_snapshots(older, newer)["verdict"] == "widened"


def test_cli_measure_and_diff(tmp_path):
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    (work / ".sopcontrol" / "rules" / "candidates.yaml").unlink(missing_ok=True)
    assert main(["growth", "measure", str(work)]) == 0
    # 再打一帧（audit 生长后）
    run_audit(work, SENSORS, DETECTORS, persist=True)
    assert main(["growth", "measure", str(work)]) == 0
    assert main(["growth", "diff", str(work)]) == 0
    assert len(load_space_snapshots(work)) >= 2


def test_ambient_audit_appends_light_snapshot(tmp_path):
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    (work / ".sopcontrol" / "rules" / "candidates.yaml").unlink(missing_ok=True)
    run_audit(work, SENSORS, DETECTORS, persist=True)
    snaps = load_space_snapshots(work)
    assert snaps
    assert snaps[-1].source == "ambient"
    assert snaps[-1].bypass_open >= 1

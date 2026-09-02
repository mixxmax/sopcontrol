"""LP2：入口薄清单与 redundant_entry_point 双域命中。"""
from __future__ import annotations

import shutil
from pathlib import Path

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit
from sopcontrol.cli import main
from sopcontrol.inventory import build_entry_inventory

ROOT = Path(__file__).resolve().parents[2]


def test_redundant_entry_point_on_jobflow_and_ci(tmp_path):
    hits = {}
    for name, rule_id in (("jobflow-preview", "PUSH-002"), ("ci-deploy", "RELEASE-001")):
        work = tmp_path / name
        shutil.copytree(ROOT / "corpus" / "fixtures" / name, work)
        report = run_audit(work, SENSORS, DETECTORS, persist=False)
        patterns = {f.pattern_id for f in report.findings if f.rule_id == rule_id}
        hits[name] = patterns
        assert "redundant_entry_point" in patterns
        assert "legacy_entry_alive" not in patterns
    assert hits["jobflow-preview"] and hits["ci-deploy"]


def test_inventory_flags_delete_first(tmp_path):
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    inv = build_entry_inventory(work, SENSORS, DETECTORS)
    push2 = next(r for r in inv["rows"] if r["rule_id"] == "PUSH-002")
    assert push2["redundant_entry"] is True
    assert push2["delete_first"] is True
    assert inv["redundant_entry_points"] >= 1
    assert inv["delete_first_actions"] >= 1


def test_inventory_cli(tmp_path, capsys):
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "ci-deploy", work)
    assert main(["inventory", str(work)]) == 0
    out = capsys.readouterr().out
    assert "冗余入口" in out
    assert "RELEASE-001" in out or "应删旁路" in out

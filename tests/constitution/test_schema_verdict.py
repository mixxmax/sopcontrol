"""schema_field_unread 进入吸收判定 → gap。"""
from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit
from pathlib import Path
import shutil


def test_unread_schema_field_is_gap(tmp_path):
    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/shop-checkout", work)
    report = run_audit(work, SENSORS, DETECTORS, persist=False)
    v = next(x for x in report.verdicts if x.rule_id == "REFUND-009")
    assert v.status == "gap"
    assert any(f.pattern_id == "schema_field_unread" for f in report.findings if f.rule_id == "REFUND-009")

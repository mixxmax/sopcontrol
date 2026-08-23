"""语料表驱动测试：每条用例 = 模式 × 夹具 × 期望判定（expected_verdict 即断言）。"""
from pathlib import Path

import pytest
import yaml

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit

ROOT = Path(__file__).resolve().parents[2]
CASES = yaml.safe_load((ROOT / "corpus" / "cases.yaml").read_text(encoding="utf-8"))["cases"]


def test_corpus_is_nonempty():
    assert CASES, "语料为空——fail-on-empty 守卫（OPA --fail-on-empty 同款教训）"


def run_case(fixture: str):
    return run_audit(ROOT / "corpus" / "fixtures" / fixture, SENSORS, DETECTORS)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
def test_case(case):
    report = run_case(case["fixture"])

    verdict = next(v for v in report.verdicts if v.rule_id == case["rule_id"])
    expected = case["expected_verdict"]
    assert verdict.status == expected["status"]
    actual_absorption = verdict.absorption.value if verdict.absorption else None
    assert actual_absorption == expected["absorption"]

    actual_findings = {
        (f.pattern_id, f.severity) for f in report.findings if f.rule_id == case["rule_id"]
    }
    expected_findings = {
        (f["pattern_id"], f["severity"]) for f in case["expected_findings"]
    }
    assert actual_findings == expected_findings, (
        f"{case['case_id']} finding 不符: 期望 {expected_findings}, 实际 {actual_findings}"
    )

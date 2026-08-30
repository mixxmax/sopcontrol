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


def test_case_ids_are_unique():
    """重复 case_id 会虚报覆盖率：语料就是测试集，条数是「补了多少对照」的唯一度量。

    重复项每条都会通过（同夹具同规则同期望），于是分母悄悄变大而判断力没变——
    这正是 16.4 治理幻觉在语料层的形态：指标涨了，控制力没涨。
    """
    ids = [c["case_id"] for c in CASES]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"重复的 case_id: {dupes}"


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

    if "expected_grounding" in case:
        assert verdict.grounding == case["expected_grounding"], (
            f"{case['case_id']} 依据强度不符: 期望 {case['expected_grounding']}, 实际 {verdict.grounding}"
        )
        # 自曝必须进 reason：用户读的是渲染出来的那句话，不是 pydantic 字段
        if verdict.grounding:
            assert "判定依据" in verdict.reason, (
                f"{case['case_id']} 有 grounding 字段但 reason 未自曝依据强度"
            )

    actual_findings = {
        (f.pattern_id, f.severity) for f in report.findings if f.rule_id == case["rule_id"]
    }
    expected_findings = {
        (f["pattern_id"], f["severity"]) for f in case["expected_findings"]
    }
    assert actual_findings == expected_findings, (
        f"{case['case_id']} finding 不符: 期望 {expected_findings}, 实际 {actual_findings}"
    )


def test_pass_cases_declare_grounding():
    """每个正向判定必须声明依据强度——16.4 输出层防线在语料层的落实。

    pass 打印出来都一样好看，但 structural 验证了代码结构、lexical 只搜到了
    字符串。语料不逐条声明 expected_grounding，这条差别就无人看守，跨语言
    的 pass 会永远顶着一个和 Python 一样可信的脸。
    """
    missing = [
        c["case_id"] for c in CASES
        if c["expected_verdict"]["status"] == "pass" and "expected_grounding" not in c
    ]
    assert not missing, f"pass 用例缺 expected_grounding: {missing}"
    bad = [
        c["case_id"] for c in CASES
        if "expected_grounding" in c
        and c["expected_grounding"] not in ("structural", "lexical", "mixed")
    ]
    assert not bad, f"expected_grounding 取值越界: {bad}"

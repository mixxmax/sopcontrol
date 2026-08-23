"""宪法测试：判定器的可解释性、确定性、fail-closed 与 enforced 克制。"""
from pathlib import Path

import yaml

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit
from sopcontrol.model import Absorption, Modality, Rule, RuleStatus, SourceRef
from sopcontrol.verdict import evaluate_rule

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "corpus" / "fixtures"
CASES = yaml.safe_load((ROOT / "corpus" / "cases.yaml").read_text(encoding="utf-8"))["cases"]


def run_case(fixture: str):
    return run_audit(FIXTURES / fixture, SENSORS, DETECTORS)


def make_rule(**overrides) -> Rule:
    base = dict(
        rule_id="TEST-001",
        statement="测试规则必须被接线",
        modality=Modality.MUST,
        status=RuleStatus.accepted,
        source=SourceRef(type="manual_seed", ref="tests"),
        consumer_markers=["some_marker"],
    )
    base.update(overrides)
    return Rule(**base)


def all_corpus_verdicts():
    fixtures = sorted({c["fixture"] for c in CASES})
    for fixture in fixtures:
        report = run_audit(ROOT / "corpus" / "fixtures" / fixture, SENSORS, DETECTORS)
        for v in report.verdicts:
            yield v


def test_every_verdict_is_explainable():
    for v in all_corpus_verdicts():
        assert v.reason.strip(), f"{v.rule_id} 判定缺少理由"
        assert v.next_action.strip(), f"{v.rule_id} 判定缺少下一步"
        assert v.rule_ids == [v.rule_id]


def test_verdict_is_deterministic():
    rule = make_rule()
    a = evaluate_rule(rule, [], [])
    b = evaluate_rule(rule, [], [])
    assert a.model_dump() == b.model_dump()


def test_fail_closed_on_missing_evidence():
    """已接受的 MUST 规则 + 零证据 → 只能是 gap/unknown，绝不可能是通过。"""
    verdict = evaluate_rule(make_rule(), [], [])
    assert verdict.status in ("gap", "unknown")
    assert verdict.absorption != Absorption.wired_and_tested
    assert verdict.absorption != Absorption.enforced


def test_enforced_is_never_issued_in_v0():
    """enforced 需要运行时 trace 证据（手册 6.5 七条件）；v0 的最高等级是 wired_and_tested。"""
    for v in all_corpus_verdicts():
        assert v.absorption != Absorption.enforced


def test_positive_control_is_not_false_blocked():
    """正向对照必须能通过——检测器不得变成"见谁都报警"。"""
    report = run_case("shop-checkout")
    verdict = next(v for v in report.verdicts if v.rule_id == "REFUND-001")
    assert verdict.status == "pass"
    assert verdict.absorption == Absorption.wired_and_tested

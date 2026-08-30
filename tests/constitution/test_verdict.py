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


def test_grounding_classification():
    """依据强度分类：全结构化/全词法/混合/无证据，按最弱承重取值。"""
    from sopcontrol.model import Evidence
    from sopcontrol.verdict import evidence_grounding

    def ev(kind):
        return Evidence(kind=kind, subject="x.py", observed=[], observer="t", input_hash="h")

    assert evidence_grounding([]) is None
    assert evidence_grounding([ev("ast_scan.references")]) == "structural"
    assert evidence_grounding([ev("go_scan.references")]) == "lexical"
    assert evidence_grounding([ev("code_scan.identifiers")]) == "lexical"
    assert evidence_grounding([ev("ast_scan.references"), ev("go_scan.references")]) == "mixed"


def test_python_pass_discloses_structural():
    """Python 夹具的 pass 自曝结构化依据。"""
    report = run_case("shop-checkout")
    verdict = next(v for v in report.verdicts if v.rule_id == "REFUND-001")
    assert verdict.grounding == "structural"
    assert "判定依据" in verdict.reason and "结构化" in verdict.reason


def test_go_pass_discloses_lexical_proxy():
    """Go 夹具的 pass 必须自曝词法代理——16.4 的输出层防线。

    治理幻觉的输出层形态：Go 规则的 pass 和 Python 规则的 pass 打印得一模
    一样，但一个验证了代码结构、一个只是标识符在剥掉注释的文本里出现过。
    判定器不验证调用关系（零 I/O），但它必须如实说出它凭什么判 pass。
    """
    report = run_case("go-gateway")
    verdict = next(v for v in report.verdicts if v.rule_id == "GO-001")
    assert verdict.status == "pass"
    assert verdict.grounding == "lexical"
    assert "词法代理" in verdict.reason and "未验证调用关系" in verdict.reason


def test_verdict_without_consumer_evidence_has_no_grounding():
    """无消费证据的判定（unknown/gap-documented）不假装有依据强度。"""
    verdict = evaluate_rule(make_rule(), [], [])
    assert verdict.grounding is None
    assert "判定依据" not in verdict.reason

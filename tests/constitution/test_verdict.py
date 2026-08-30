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


def test_go_pass_discloses_structural():
    """Go 夹具的 pass 在 go_ast 深度化后自曝结构化依据。

    go_ast_scan（tree-sitter）就位后，Go 消费证据与 Python 同级：同包互见 +
    import 闭包可达，测试替身（CASE-047）进不了这个信用等级。
    """
    report = run_case("go-gateway")
    verdict = next(v for v in report.verdicts if v.rule_id == "GO-001")
    assert verdict.status == "pass"
    assert verdict.grounding == "structural"
    assert "判定依据" in verdict.reason and "结构化" in verdict.reason


def test_ts_pass_still_discloses_lexical_proxy():
    """TS 夹具尚无结构化扫描器——pass 必须继续自曝词法代理，不许蹭 Go 的升级。

    治理幻觉的输出层形态：Go 升级后若 TS 的 pass 顶着一模一样的脸，用户就
    分不清哪个验证了代码结构、哪个只是标识符在剥掉注释的文本里出现过。
    """
    report = run_case("web-gate")
    verdict = next(v for v in report.verdicts if v.rule_id == "GATE-001")
    assert verdict.status == "pass"
    assert verdict.grounding == "lexical"
    assert "词法代理" in verdict.reason and "未验证调用关系" in verdict.reason


def test_go_test_double_cannot_reach_consumer():
    """Go 同名替身（package api 自定义 PostCharge）必须被可达性识破。

    替身文件能编译、测试能全绿——生产实现从未被 import。go_ast 的包/import
    证据让 go_import_closure 走不到 src/charge.go，回归信用被收回退回 wired。
    """
    report = run_case("go-gateway")
    verdict = next(v for v in report.verdicts if v.rule_id == "GO-004")
    assert verdict.status == "gap"
    assert verdict.absorption == Absorption.wired
    assert verdict.grounding == "structural"
    assert any(
        f.pattern_id == "test_cannot_reach_consumer" and f.rule_id == "GO-004"
        for f in report.findings
    )


def test_verdict_without_consumer_evidence_has_no_grounding():
    """无消费证据的判定（unknown/gap-documented）不假装有依据强度。"""
    verdict = evaluate_rule(make_rule(), [], [])
    assert verdict.grounding is None
    assert "判定依据" not in verdict.reason

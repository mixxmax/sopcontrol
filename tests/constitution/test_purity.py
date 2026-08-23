"""宪法测试：判定器是纯函数——无 I/O。挑衅方式：把 open 炸掉后判定必须照常工作。"""
import builtins

from sopcontrol.model import Evidence, Modality, Rule, RuleStatus, SourceRef
from sopcontrol.verdict import evaluate_rule, evaluate_all


def make_rule_and_evidence():
    rule = Rule(
        rule_id="PURE-001",
        statement="纯度测试规则必须被接线",
        modality=Modality.MUST,
        status=RuleStatus.accepted,
        source=SourceRef(type="manual_seed", ref="tests"),
        consumer_markers=["pure_marker"],
    )
    evidence = [
        Evidence(
            kind="ast_scan.references",
            subject="src/app.py",
            observed=["pure_marker", "other"],
            observer="ast_scan",
            input_hash="abc123",
        ),
        Evidence(
            kind="ast_scan.references",
            subject="tests/test_app.py",
            observed=["pure_marker"],
            observer="ast_scan",
            input_hash="def456",
        ),
        Evidence(
            kind="code_scan.identifiers",
            subject="src/app.py",
            observed=["pure_marker", "other"],
            observer="code_scan",
            input_hash="abc123",
        ),
    ]
    return rule, evidence


def test_verdict_does_no_io(monkeypatch):
    def no_open(*args, **kwargs):
        raise AssertionError("判定器不得做任何 I/O（宪法：纯函数）")

    monkeypatch.setattr(builtins, "open", no_open)
    rule, evidence = make_rule_and_evidence()
    verdict = evaluate_all([rule], evidence, [])[0]
    assert verdict.status == "pass"

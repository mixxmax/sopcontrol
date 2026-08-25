"""语料/文档不得充当生产消费者（垂直骨干役用教训）。"""
from plugins.detectors.state_health import finding_write_only_state
from sopcontrol.context import is_meta_path, is_production_path, is_test_path
from sopcontrol.model import Evidence, Modality, Rule, RuleStatus, SourceRef
from sopcontrol.verdict import consumer_evidence, evaluate_rule


def test_meta_path_helpers():
    assert is_meta_path("corpus/patterns.yaml")
    assert is_meta_path("docs/SOP.md")
    assert not is_production_path("corpus/patterns.yaml")
    assert is_production_path("plugins/detectors/state_health.py")
    assert is_test_path("tests/patterns/test_state_patterns.py")


def test_corpus_hit_does_not_wire_rule():
    # 用 __name__ 取标记，同时让 AST 看到 finding_write_only_state（避免 comment_only 误报）
    marker = finding_write_only_state.__name__
    rule = Rule(
        rule_id="R-1",
        statement="x",
        modality=Modality.MUST,
        status=RuleStatus.accepted,
        source=SourceRef(type="manual_seed", ref="t"),
        consumer_markers=[marker],
    )
    evidence = [
        Evidence(
            kind="code_scan.identifiers",
            subject="corpus/patterns.yaml",
            observed=[marker],
            observer="code_scan",
            input_hash="h1",
        )
    ]
    prod, test = consumer_evidence(rule, evidence)
    assert prod == [] and test == []
    v = evaluate_rule(rule, evidence, [])
    assert v.status == "gap" and v.absorption and v.absorption.value == "documented"

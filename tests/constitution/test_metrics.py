"""sopctl metrics 的机制测试：分母是语料、unmeasurable 不填 0、分布口径正确。

不重跑全量语料（test_cases.py 已逐条断言），只验证度量机制本身：
计数、分组、grounding 分布与 unmeasurable 清单的诚实性。
"""
import yaml

from plugins import DETECTORS, SENSORS
from sopcontrol.metrics import UNMEASURABLE, build_snapshot, run_corpus_cases

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
CASES = yaml.safe_load((ROOT / "corpus" / "cases.yaml").read_text(encoding="utf-8"))["cases"]


def test_snapshot_counts_and_accuracy_on_subset():
    """小样本子集上的计数与分组：正向、负向、跨语言各取一条。"""
    import tempfile
    from pathlib import Path

    subset = [c for c in CASES if c["case_id"] in ("CASE-002", "CASE-001", "CASE-024")]
    with tempfile.TemporaryDirectory() as td:
        tmp_cases = Path(td) / "cases.yaml"
        tmp_cases.write_text(
            yaml.safe_dump({"cases": subset}, allow_unicode=True), encoding="utf-8"
        )
        snapshot = build_snapshot(
            cases_path=tmp_cases,
            fixtures_root=ROOT / "corpus" / "fixtures",
            enforce_mutations=False,
        )
    t = snapshot["totals"]
    assert t["cases"] == 3
    assert t["verdict_match"] == 3, "语料用例在度量口径下必须与标注相符"
    assert t["accuracy"] == 1.0
    # 按夹具分组：三条用例来自三个夹具
    assert set(snapshot["by_fixture"]) == {"shop-checkout", "jobflow-preview", "go-gateway"}
    # 负向对照（无期望 finding）进了独立桶：CASE-002 与 CASE-024 都是
    assert snapshot["by_pattern"]["no_finding_expected"]["cases"] == 2
    # go-gateway 的 pass 在 go_ast 深度化后是结构化证据
    assert snapshot["grounding_distribution"].get("structural") == 2
    assert snapshot["grounding_distribution"].get("none") == 1


def test_unmeasurable_never_fakes_zero():
    """算不出的指标必须挂真实理由，绝不允许用 0 冒充测过——16.4。"""
    assert UNMEASURABLE, "unmeasurable 清单为空：要么全测了（不可能，无真实使用数据），要么在撒谎"
    for item in UNMEASURABLE:
        assert item["metric"] and item["reason"], f"缺理由的 unmeasurable 项: {item}"


def test_case_results_carry_grounding():
    """逐用例结果必须带上依据强度——度量自己也要用上自曝字段，而不是只打印给人看。"""
    subset = [c for c in CASES if c["case_id"] in ("CASE-002", "CASE-017", "CASE-024", "CASE-048")]
    results = run_corpus_cases(subset, ROOT / "corpus" / "fixtures", SENSORS, DETECTORS)
    by_case = {r["case_id"]: r for r in results}
    assert by_case["CASE-002"]["actual"]["grounding"] == "structural"
    assert by_case["CASE-017"]["actual"]["grounding"] == "structural"  # ts_ast 深度化后
    assert by_case["CASE-024"]["actual"]["grounding"] == "structural"  # go_ast 深度化后
    assert by_case["CASE-048"]["actual"]["grounding"] == "lexical"  # .js 家族永留词法层
    assert all(r["verdict_match"] for r in results)

"""变异验证：负向对照必须能被证伪。

负向对照（expected_findings: []）断言「检测器在正确代码上保持沉默」，但沉默有两种
来源——判断（看懂了这段代码是对的）和无能（压根没看见这里）——在测试输出里都是绿的。
唯一的区分办法是把当初的修复退回去看沉默是否变成告警。

这个文件让 corpus/mutations.yaml 的声明真的跑起来：
  · test_mutation_makes_controls_fire —— 逐条退回，断言声明的对照确实报警
  · test_every_negative_control_is_covered —— 反过来守卫：没有对照能白拿绿色
  · test_declarations_and_mutators_agree —— YAML 与变异器实现一一对应，不许单边漂移
"""
from pathlib import Path

import pytest
import yaml

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit

from mutations import MUTATORS  # 同目录模块；tests/corpus 无 __init__.py，由 pytest 置入 sys.path

ROOT = Path(__file__).resolve().parents[2]
MUTATIONS = yaml.safe_load(
    (ROOT / "corpus" / "mutations.yaml").read_text(encoding="utf-8")
)["mutations"]
CASES = {
    c["case_id"]: c
    for c in yaml.safe_load(
        (ROOT / "corpus" / "cases.yaml").read_text(encoding="utf-8")
    )["cases"]
}


def test_mutations_are_nonempty():
    assert MUTATIONS, "变异声明为空——负向对照又变回无人验证的散文"


def test_declarations_and_mutators_agree():
    """声明与实现单边漂移都是幻觉：YAML 里写了没实现 = 没在跑；实现了没声明 = 没人读。"""
    declared = {m["mutation_id"] for m in MUTATIONS}
    implemented = set(MUTATORS)
    assert declared == implemented, (
        f"只声明未实现: {sorted(declared - implemented)}；"
        f"只实现未声明: {sorted(implemented - declared)}"
    )


def test_every_negative_control_is_covered():
    """每条零 finding 的用例都必须被至少一次变异覆盖。

    这是覆盖率指标的修正：此前的脚本数的是「有几条零 finding 用例」和 ground_truth
    散文，那度量的是语料条数，不是控制力——16.4 治理幻觉在语料层的形态。真正该问的
    是「这条对照如果失效，会不会有测试变红」。
    """
    negative = {
        cid for cid, c in CASES.items() if not c["expected_findings"]
    }
    covered = {
        item["case_id"] for m in MUTATIONS for item in m["must_fire"]
    }
    uncovered = sorted(negative - covered)
    assert not uncovered, (
        f"以下负向对照没有任何变异能证伪它，绿色不代表检测器看得见: {uncovered}"
    )


def test_must_fire_targets_are_negative_controls():
    """变异只能拿零 finding 的用例当靶子：本来就报警的用例证明不了任何东西。"""
    bad = []
    for m in MUTATIONS:
        for item in m["must_fire"]:
            case = CASES.get(item["case_id"])
            if case is None:
                bad.append(f"{m['mutation_id']}→{item['case_id']}（用例不存在）")
            elif case["expected_findings"]:
                bad.append(f"{m['mutation_id']}→{item['case_id']}（本来就有 finding）")
    assert not bad, f"无效靶子: {bad}"


def _fired(fixture: str, rule_id: str) -> set[str]:
    report = run_audit(ROOT / "corpus" / "fixtures" / fixture, SENSORS, DETECTORS)
    return {f.pattern_id for f in report.findings if f.rule_id == rule_id}


@pytest.mark.parametrize(
    "mutation", MUTATIONS, ids=lambda m: m["mutation_id"]
)
def test_mutation_makes_controls_fire(mutation, monkeypatch):
    mutate = MUTATORS[mutation["mutation_id"]]
    silent = []
    for item in mutation["must_fire"]:
        case = CASES[item["case_id"]]
        # 先确认未变异时确实沉默：若这里就报警，说明夹具或期望已漂移，
        # 后面的「变异后报警」会假绿（报的是同一条一直存在的 finding）。
        before = _fired(case["fixture"], case["rule_id"])
        assert item["pattern_id"] not in before, (
            f"{item['case_id']} 未变异时已报 {item['pattern_id']}，靶子失效"
        )
        with monkeypatch.context() as mp:
            mutate(mp)
            after = _fired(case["fixture"], case["rule_id"])
        if item["pattern_id"] not in after:
            silent.append(f"{item['case_id']}（期望 {item['pattern_id']}，实际 {sorted(after)}）")
    assert not silent, (
        f"{mutation['mutation_id']} 退回「{mutation['revert']}」后仍然沉默：{silent}\n"
        f"这些对照并不守卫「{mutation['fix']}」——检测器可能压根没看见这段代码。"
    )

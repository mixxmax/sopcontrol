"""reachability 检测器：测试路径的消费者引用是否真能到达生产实现（R1 收口）。

断口的形状：判定器给「回归证据」记分的依据，是测试文件里出现了消费者标记这个
**标识符**。标识符是可达性的代理，而这个代理从不检查可达性——测试里写着
`consumer_marker` 四个字就算测过了，哪怕它导入的模块与定义 `consumer_marker` 的
生产文件之间没有任何 import 路径。于是把生产端的函数改名、或删掉那行 import，
测试照旧全绿，规则照旧停在 wired_and_tested：这正是 SELF-001 bypass_note 里
自己登记的 R1「改名即可让本规则看起来仍满足」。

本检测器用 import_graph 的邻接做传递闭合，回答一个更硬的问题：从这个测试文件
出发，沿 import 边走下去，能不能走到任何一个含该标记的生产文件。走不到就报
test_cannot_reach_consumer，判定器据此把测试信用收回。

沉默的边界（过度告警与漏报对称）：只在两侧都有 Python 证据、且测试文件确实留下
了 import 证据时才发声。传感器只在 import 非空时铸证据，所以「查不到邻接」既可能
是真的没导入、也可能是没解析成功——分不清就不报，与 state_health._write_sites
的取舍同源：宁可保留既有信用，也不假装自己看得见。
"""
from __future__ import annotations

from sopcontrol.context import is_production_path, is_test_path
from sopcontrol.model import Evidence, Finding, Rule, RuleStatus
from sopcontrol.verdict import HARD_MODALITIES, marker_hit

from plugins.sensors.import_graph import (
    build_adjacency,
    import_closure,
    index_by_module,
    module_names,
)

GOVERNANCE_ACTIVE = {
    RuleStatus.accepted,
    RuleStatus.compiled,
    RuleStatus.activated,
    RuleStatus.monitored,
}


def finding_test_cannot_reach_consumer(
    rule: Rule,
    test_files: list[str],
    prod_files: list[str],
    evidence_ids: list[str],
) -> Finding:
    """具名工厂：pattern_id 字符串不算接线（SELF-001/002 的教训）。"""
    markers = ", ".join(rule.consumer_markers)
    return Finding(
        pattern_id="test_cannot_reach_consumer",
        rule_id=rule.rule_id,
        summary=(
            f"测试路径引用了 [{markers}]，但 {', '.join(test_files)} 的 import 闭包"
            f"到不了定义它的生产文件（{', '.join(prod_files)}）："
            f"回归信用建立在标识符巧合上，改名或删 import 都不会让测试变红"
        ),
        severity="gap",
        detector="reachability",
        evidence_ids=evidence_ids,
    )


def _python_marker_files(
    rule: Rule, evidence: list[Evidence]
) -> tuple[list[Evidence], list[Evidence]]:
    """(生产侧, 测试侧) 命中标记的 Python AST 证据。"""
    prod, test = [], []
    for ev in evidence:
        if ev.kind != "ast_scan.references" or not ev.subject.endswith(".py"):
            continue
        if not marker_hit(ev, rule.consumer_markers):
            continue
        if is_test_path(ev.subject):
            test.append(ev)
        elif is_production_path(ev.subject):
            prod.append(ev)
    return prod, test


class ReachabilityDetector:
    detector_id = "reachability"

    def detect(self, rules: list[Rule], evidence: list[Evidence]) -> list[Finding]:
        adjacency = build_adjacency(evidence)
        if not adjacency:
            return []  # 无 import 证据（非 Python 项目或全不可解析）：不假装看得见
        # 索引覆盖全部 .py 主体而非仅有 import 的文件：叶子模块（只被导入、自己不
        # 导入任何东西）在 adjacency 里没有条目，但它完全可以是标记的定义处。
        py_files = sorted(
            {
                e.subject for e in evidence
                if e.kind == "ast_scan.references" and e.subject.endswith(".py")
            }
            | set(adjacency)
        )
        by_module = index_by_module(py_files)

        findings: list[Finding] = []
        for rule in rules:
            if rule.status not in GOVERNANCE_ACTIVE or rule.modality not in HARD_MODALITIES:
                continue
            if not rule.consumer_markers:
                continue
            prod, test = _python_marker_files(rule, evidence)
            if not prod or not test:
                continue  # 缺一侧由 no_consumer 的 documented_* 模式负责，不重复告警
            prod_subjects = {e.subject for e in prod}
            # 只看留下了 import 证据的测试文件：没证据 ≠ 到不了
            visible = [e for e in test if e.subject in adjacency]
            if not visible:
                continue
            reaching = []
            for ev in visible:
                modules, files = import_closure(ev.subject, adjacency, by_module)
                hit = prod_subjects & files
                if not hit:
                    # 文件级没连上时退一步看顶层名：邻接记的是裸顶层名，
                    # 包内文件（src/spec/validator.py）要靠名字对齐才认得出。
                    hit = {
                        s for s in prod_subjects
                        if modules & module_names(s)
                    }
                if hit:
                    reaching.append(ev.subject)
            if reaching:
                continue
            findings.append(
                finding_test_cannot_reach_consumer(
                    rule,
                    sorted(e.subject for e in visible),
                    sorted(prod_subjects),
                    [e.evidence_id for e in prod + visible],
                )
            )
        return findings

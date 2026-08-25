"""state_health 检测器：状态字段健康模式（手册 5.8 / 14.1 场景3 的标识符级形态）。

write_only_state / state_in_parallel_files 都是 grep 级代理证据：
单文件出现不排除同文件内读写，跨文件同名不排除刻意镜像——severity 如实分级
（info/gap），verdict 不消费这些 finding（模式语义成熟后再接入吸收等级）。
"""
from __future__ import annotations

from sopcontrol.context import is_production_path, is_test_path
from sopcontrol.model import Evidence, Finding, Rule
from sopcontrol.verdict import HARD_MODALITIES, marker_hit


def _occurrences(rule: Rule, evidence: list[Evidence]) -> tuple[list[str], list[str]]:
    """返回 (出现该状态标记的生产文件, 测试文件)；语料/文档不计。"""
    prod, test = [], []
    for ev in evidence:
        if not marker_hit(ev, rule.state_markers):
            continue
        if is_test_path(ev.subject):
            test.append(ev.subject)
        elif is_production_path(ev.subject):
            prod.append(ev.subject)
    return prod, test


def finding_write_only_state(rule_id: str, markers: str, prod0: str) -> Finding:
    """SELF-001 生产消费者：具名函数供 AST 引用（字符串 pattern_id 不算接线）。"""
    return Finding(
        pattern_id="write_only_state",
        rule_id=rule_id,
        summary=(
            f"状态标记 [{markers}] 仅出现在单一生产文件 {prod0}，"
            f"无其他消费者读取迹象（14.1 场景3 的标识符级代理）"
        ),
        severity="info",
        detector="state_health",
    )


def finding_state_in_parallel_files(rule_id: str, markers: str, prod: list[str]) -> Finding:
    """SELF-002 生产消费者：具名函数供 AST 引用。"""
    return Finding(
        pattern_id="state_in_parallel_files",
        rule_id=rule_id,
        summary=(
            f"状态标记 [{markers}] 并行出现在 {len(prod)} 个生产文件 "
            f"({', '.join(sorted(prod))})：双处维护，真源不明（手册 5.8）"
        ),
        severity="gap",
        detector="state_health",
    )


def finding_state_marker_absent(rule_id: str, markers: str) -> Finding:
    return Finding(
        pattern_id="state_marker_absent",
        rule_id=rule_id,
        summary=f"状态标记 [{markers}] 在代码中完全不存在（写了但没建，或已改名）",
        severity="info",
        detector="state_health",
    )


class StateHealthDetector:
    detector_id = "state_health"

    def detect(self, rules: list[Rule], evidence: list[Evidence]) -> list[Finding]:
        findings: list[Finding] = []
        for rule in rules:
            if not rule.state_markers or rule.modality not in HARD_MODALITIES:
                continue
            prod, test = _occurrences(rule, evidence)
            markers = ", ".join(rule.state_markers)

            if not prod and not test:
                findings.append(finding_state_marker_absent(rule.rule_id, markers))
            elif len(prod) == 1 and not test:
                findings.append(finding_write_only_state(rule.rule_id, markers, prod[0]))
            elif len(prod) >= 2:
                findings.append(finding_state_in_parallel_files(rule.rule_id, markers, prod))
        return findings

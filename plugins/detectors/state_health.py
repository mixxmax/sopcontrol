"""state_health 检测器：状态字段健康模式（手册 5.8 / 14.1 场景3 的标识符级形态）。

write_only_state / state_in_parallel_files 都是 grep 级代理证据：
单文件出现不排除同文件内读写，跨文件同名不排除刻意镜像——severity 如实分级
（info/gap），verdict 不消费这些 finding（模式语义成熟后再接入吸收等级）。
"""
from __future__ import annotations

from sopcontrol.context import is_test_path
from sopcontrol.model import Evidence, Finding, Rule
from sopcontrol.verdict import HARD_MODALITIES


def _occurrences(rule: Rule, evidence: list[Evidence]) -> tuple[list[str], list[str]]:
    """返回 (出现该状态标记的生产文件, 测试文件)。"""
    prod, test = [], []
    for ev in evidence:
        if ev.kind != "code_scan.identifiers":
            continue
        if any(m in (ev.observed or []) for m in rule.state_markers):
            (test if is_test_path(ev.subject) else prod).append(ev.subject)
    return prod, test


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
                findings.append(
                    Finding(
                        pattern_id="state_marker_absent",
                        rule_id=rule.rule_id,
                        summary=f"状态标记 [{markers}] 在代码中完全不存在（写了但没建，或已改名）",
                        severity="info",
                        detector=self.detector_id,
                    )
                )
            elif len(prod) == 1 and not test:
                findings.append(
                    Finding(
                        pattern_id="write_only_state",
                        rule_id=rule.rule_id,
                        summary=(
                            f"状态标记 [{markers}] 仅出现在单一生产文件 {prod[0]}，"
                            f"无其他消费者读取迹象（14.1 场景3 的标识符级代理）"
                        ),
                        severity="info",
                        detector=self.detector_id,
                    )
                )
            elif len(prod) >= 2:
                findings.append(
                    Finding(
                        pattern_id="state_in_parallel_files",
                        rule_id=rule.rule_id,
                        summary=(
                            f"状态标记 [{markers}] 并行出现在 {len(prod)} 个生产文件 "
                            f"({', '.join(sorted(prod))})：双处维护，真源不明（手册 5.8）"
                        ),
                        severity="gap",
                        detector=self.detector_id,
                    )
                )
        return findings

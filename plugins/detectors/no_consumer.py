"""no_consumer 检测器：规则吸收断口的模式识别。

产出的 Finding 是建议性记录；判定器（verdict.py）独立从证据推导吸收等级，不信任本检测器。
"""
from __future__ import annotations

from sopcontrol.context import is_test_path
from sopcontrol.model import Absorption, Evidence, Finding, Modality, Rule, RuleStatus
from sopcontrol.verdict import HARD_MODALITIES, consumer_evidence, legacy_evidence
GOVERNANCE_ACTIVE = {
    RuleStatus.accepted,
    RuleStatus.compiled,
    RuleStatus.activated,
    RuleStatus.monitored,
}


class NoConsumerDetector:
    detector_id = "no_consumer"

    def detect(self, rules: list[Rule], evidence: list[Evidence]) -> list[Finding]:
        findings: list[Finding] = []
        id_evidence = [e for e in evidence if e.kind == "code_scan.identifiers"]
        ast_by_subject = {
            e.subject: e for e in evidence if e.kind == "ast_scan.references"
        }
        for rule in rules:
            if rule.status not in GOVERNANCE_ACTIVE or rule.modality not in HARD_MODALITIES:
                continue
            if not rule.consumer_markers and rule.state_markers:
                continue  # 状态类规则由 state_health 检测器评估
            if not rule.consumer_markers:
                findings.append(
                    Finding(
                        pattern_id="consumer_markers_undefined",
                        rule_id=rule.rule_id,
                        summary=f"规则 {rule.rule_id} 已接受但未声明 consumer_markers，无法判定吸收",
                        severity="info",
                        detector=self.detector_id,
                    )
                )
                continue
            prod, test = consumer_evidence(rule, evidence)
            markers = ", ".join(rule.consumer_markers)
            if not prod and not test:
                findings.append(
                    Finding(
                        pattern_id="documented_rule_no_consumer",
                        rule_id=rule.rule_id,
                        summary=f"已接受的 {rule.modality.value} 规则在生产与测试路径均无消费者 [{markers}]",
                        severity="gap",
                        detector=self.detector_id,
                    )
                )
            elif not prod:
                findings.append(
                    Finding(
                        pattern_id="test_helper_only",
                        rule_id=rule.rule_id,
                        summary=f"消费者 [{markers}] 仅出现在测试路径，疑似测试 helper 掩盖生产缺口",
                        severity="gap",
                        detector=self.detector_id,
                        evidence_ids=[e.evidence_id for e in test],
                    )
                )
            elif not test:
                findings.append(
                    Finding(
                        pattern_id="documented_rule_untested",
                        rule_id=rule.rule_id,
                        summary=f"生产消费者 [{markers}] 已接线但无回归证据",
                        severity="gap",
                        detector=self.detector_id,
                        evidence_ids=[e.evidence_id for e in prod],
                    )
                )
            # 注释/字符串里的标记不算消费者：grep 命中但 AST 未命中的 .py 文件
            for grep_ev in id_evidence:
                if not grep_ev.subject.endswith(".py"):
                    continue
                if not any(m in (grep_ev.observed or []) for m in rule.consumer_markers):
                    continue
                ast_ev = ast_by_subject.get(grep_ev.subject)
                ast_names = ast_ev.observed if ast_ev else []
                ghost = [m for m in rule.consumer_markers if m in (grep_ev.observed or []) and m not in (ast_names or [])]
                if ghost:
                    findings.append(
                        Finding(
                            pattern_id="comment_only_reference",
                            rule_id=rule.rule_id,
                            summary=(
                                f"标记 [{', '.join(ghost)}] 在 {grep_ev.subject} 只出现于注释/字符串，"
                                f"不构成真实代码引用（首夜真实教训的模式化）"
                            ),
                            severity="gap",
                            detector=self.detector_id,
                            evidence_ids=[grep_ev.evidence_id],
                        )
                    )
            if rule.legacy_markers:
                legacy = legacy_evidence(rule, evidence)
                if legacy:
                    legacy_names = ", ".join(rule.legacy_markers)
                    findings.append(
                        Finding(
                            pattern_id="legacy_entry_alive",
                            rule_id=rule.rule_id,
                            summary=(
                                f"旧入口 [{legacy_names}] 仍在生产路径存活，"
                                f"可绕过受控入口 [{markers}]"
                            ),
                            severity="gap",
                            detector=self.detector_id,
                            evidence_ids=[e.evidence_id for e in legacy],
                        )
                    )
        return findings

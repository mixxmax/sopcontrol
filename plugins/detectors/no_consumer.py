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
        for rule in rules:
            if rule.status not in GOVERNANCE_ACTIVE or rule.modality not in HARD_MODALITIES:
                continue
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
            prod, test = consumer_evidence(rule, id_evidence)
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
            if rule.legacy_markers:
                legacy = legacy_evidence(rule, id_evidence)
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

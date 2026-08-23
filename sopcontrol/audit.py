"""审计流水线：传感器 → (账本) → 检测器 → 判定器。

测试与 CLI 共用这一条路径；persist=False 时纯内存运行，不污染目标项目。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .context import ProjectContext
from .ledger import Ledger
from .model import Evidence, Finding, Rule, Verdict
from .registry import Registry
from .verdict import evaluate_all


@dataclass
class AuditReport:
    rules: list[Rule]
    evidence: list[Evidence]
    findings: list[Finding]
    verdicts: list[Verdict]


def run_audit(
    root: Path,
    sensors: list,
    detectors: list,
    persist: bool = False,
) -> AuditReport:
    root = Path(root)
    ctx = ProjectContext(root)
    rules = Registry(root / ".sopcontrol" / "rules" / "registry.yaml").load()

    evidence: list[Evidence] = []
    for sensor in sensors:
        evidence.extend(sensor.observe(ctx))
    # 过期证据不参与当轮判定（Haft 式衰减；v0 尚无传感器设置 valid_until，机制就位）
    evidence = [e for e in evidence if not e.is_expired()]

    findings: list[Finding] = []
    for detector in detectors:
        findings.extend(detector.detect(rules, evidence))

    verdicts = evaluate_all(rules, evidence, findings)

    if persist:
        ledger = Ledger(root / ".sopcontrol" / "evidence" / "ledger.jsonl")
        for ev in evidence:
            ledger.append_evidence(ev)
        for f in findings:
            ledger.append_finding(f)

    return AuditReport(rules=rules, evidence=evidence, findings=findings, verdicts=verdicts)

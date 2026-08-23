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
from .task import TaskRecord, TransitionDecision, evaluate_transition
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


def run_task_verify(root: Path, sensors: list, detectors: list, task: TaskRecord) -> TransitionDecision:
    """完成门编排：独立审计 → 规则判定 → 纯函数迁移决策。不信任务自报。"""
    report = run_audit(root, sensors, detectors, persist=True)
    ledger = Ledger(Path(root) / ".sopcontrol" / "evidence" / "ledger.jsonl")
    tampered = ledger.path.exists() and not ledger.verify()
    verdicts = {v.rule_id: v.status for v in report.verdicts}
    return evaluate_transition(
        task, "verify",
        rule_verdicts=verdicts,
        known_rule_ids={r.rule_id for r in report.rules},
        ledger_tampered=tampered,
    )

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
    compact: bool = False,
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
        if compact:
            # 役用清理：整轮快照替换，去掉文件变更后的 stale 噪音
            ledger.replace_snapshot(evidence, findings)
        else:
            for ev in evidence:
                ledger.append_evidence(ev)
            for f in findings:
                ledger.append_finding(f)

    return AuditReport(rules=rules, evidence=evidence, findings=findings, verdicts=verdicts)


def load_controller_paths(root: Path) -> list[str]:
    """从 manifest.yaml 读控制器自身路径前缀；缺失视为空（普通项目无此概念）。"""
    import yaml

    manifest = Path(root) / ".sopcontrol" / "manifest.yaml"
    if not manifest.exists():
        return []
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    return [str(p) for p in (data.get("controller_paths") or [])]


def dirty_controller_changes(root: Path, task: TaskRecord) -> list[str]:
    """任务改动中落在控制器路径内且未提交基线的部分（git 不可用 = fail-closed 视为脏）。"""
    import subprocess

    controller = load_controller_paths(root)
    if not controller:
        return []
    touched = [
        p for p in task.changed_paths
        if any(p == c or p.startswith(c.rstrip("/") + "/") for c in controller)
    ]
    if not touched:
        return []
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--"] + touched,
            cwd=str(root), capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return touched  # git 不可用：无法证明干净 → 视为脏
    if proc.returncode != 0:
        return touched
    return touched if proc.stdout.strip() else []


def run_task_verify(root: Path, sensors: list, detectors: list, task: TaskRecord) -> TransitionDecision:
    """完成门编排：独立审计 → 规则判定 → 纯函数迁移决策。不信任务自报。"""
    report = run_audit(root, sensors, detectors, persist=True)
    ledger = Ledger(Path(root) / ".sopcontrol" / "evidence" / "ledger.jsonl")
    tampered = ledger.path.exists() and not ledger.verify()
    controller_dirty = dirty_controller_changes(Path(root), task)
    verdicts = {v.rule_id: v.status for v in report.verdicts}
    return evaluate_transition(
        task, "verify",
        rule_verdicts=verdicts,
        known_rule_ids={r.rule_id for r in report.rules},
        ledger_tampered=tampered,
        controller_dirty=controller_dirty,
    )

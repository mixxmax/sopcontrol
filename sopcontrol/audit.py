"""审计流水线：传感器 → (账本) → 检测器 → 判定器。

测试与 CLI 共用这一条路径；persist=False 时纯内存运行，不污染目标项目。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import inspect
from pathlib import Path

from .attest import attestation_evidence
from .bootstrap import maturity_evidence
from .context import ProjectContext
from .ledger import Ledger
from .model import Evidence, Finding, Rule, Verdict, effective_rules, utcnow
from .registry import Registry
from .task import TaskRecord, TransitionDecision, evaluate_transition
from .testrun import declaration_evidence
from .verdict import evaluate_all, latest_test_run


@dataclass
class AuditReport:
    rules: list[Rule]
    evidence: list[Evidence]
    findings: list[Finding]
    verdicts: list[Verdict]
    at: datetime


def run_audit(
    root: Path,
    sensors: list,
    detectors: list,
    persist: bool = False,
    compact: bool = False,
    extra_evidence: list[Evidence] | None = None,
    *,
    at: datetime | None = None,
) -> AuditReport:
    """extra_evidence：不由传感器产生、由调用方铸好送进来的证据（如完成门的 E4 测试运行）。"""
    root = Path(root)
    ctx = ProjectContext(root)
    audit_at = at or utcnow()
    rules = Registry(root / ".sopcontrol" / "rules" / "registry.yaml").load()
    current_rules = effective_rules(rules, at=audit_at)

    evidence: list[Evidence] = list(extra_evidence or [])
    # 「项目声明了测试命令」这一事实每轮都送进判定器（零成本，不跑命令）：
    # 没有它，判定器分不清「没声明」和「本轮没跑」，就会对已声明的项目给出
    # 「去声明 test_command」这种错误建议。
    decl = declaration_evidence(root)
    if decl is not None:
        evidence.append(decl)
    # 确认书的版本比对每轮重算（手册 6.5 条件5/7）：源文档改一个字节，上一轮的
    # 「文档-实现一致」就不再算数。放在这里而不是传感器里，因为它要读注册表，
    # 而传感器只看项目文件。
    evidence.extend(attestation_evidence(root, current_rules))
    # 成熟度（手册 7.3）与确认书同处一层：都要读 .sopcontrol 自身状态，传感器看不见。
    # 每轮重算而不是缓存——装了钩子、声明了验收命令，下一轮就该反映出来。
    evidence.append(maturity_evidence(root, rules, at=audit_at))
    for sensor in sensors:
        evidence.extend(sensor.observe(ctx))
    # 过期证据不参与当轮判定（Haft 式衰减；v0 尚无传感器设置 valid_until，机制就位）
    evidence = [e for e in evidence if not e.is_expired(audit_at)]

    findings: list[Finding] = []
    for detector in detectors:
        parameters = inspect.signature(detector.detect).parameters
        if "at" in parameters:
            findings.extend(detector.detect(current_rules, evidence, at=audit_at))
        else:
            findings.extend(detector.detect(current_rules, evidence))

    verdicts = evaluate_all(current_rules, evidence, findings, at=audit_at)

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

    return AuditReport(
        rules=rules, evidence=evidence, findings=findings, verdicts=verdicts, at=audit_at
    )


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


def collect_test_run(root: Path) -> list[Evidence]:
    """完成门的 E4 步骤：项目声明了 test_command 就真跑一遍，否则返回空列表。

    失败不抛异常——跑挂了要留成 passed=False 的证据让判定器降级，而不是让整个
    完成门崩掉（崩掉会被 run_gate 的 fail-closed 兜成 block，看不出是测试没过）。
    """
    from .testrun import run_test_command

    try:
        ev = run_test_command(Path(root))
    except Exception:  # noqa: BLE001 — 测试运行器本身出问题不该炸掉完成门
        return []
    return [ev] if ev is not None else []


def run_task_verify(
    root: Path,
    sensors: list,
    detectors: list,
    task: TaskRecord,
    *,
    test_evidence: list[Evidence] | None = None,
) -> TransitionDecision:
    """完成门编排：真跑测试(E4) → 独立审计 → 规则判定 → 纯函数迁移决策。不信任务自报。

    E4 只在完成门产生：普通 audit 不该每次扫描都付一次测试时间（testrun.should_run
    另有递归自锁，避免测试子进程里再套一层完成门）。调用方可先在 registry 锁外
    收集 E4，再让最终审计、当前规则复核与任务落盘共享同一锁域。
    """
    evidence = collect_test_run(root) if test_evidence is None else test_evidence
    report = run_audit(root, sensors, detectors, persist=True, extra_evidence=evidence)
    ledger = Ledger(Path(root) / ".sopcontrol" / "evidence" / "ledger.jsonl")
    tampered = ledger.path.exists() and not ledger.verify()
    controller_dirty = dirty_controller_changes(Path(root), task)
    verdicts = {v.rule_id: v.status for v in report.verdicts}
    # 迁移门是纯函数，拿不到账本；E4 事实由这里从本轮证据里摘成普通数据递进去
    ev = latest_test_run(report.evidence)
    current_rules = effective_rules(report.rules, at=report.at)
    return evaluate_transition(
        task, "verify",
        rule_verdicts=verdicts,
        known_rule_ids={rule.rule_id for rule in current_rules},
        rule_scopes={rule.rule_id: rule.scope_paths for rule in current_rules},
        ledger_tampered=tampered,
        controller_dirty=controller_dirty,
        test_run=dict(ev.observed or {}) if ev is not None else None,
    )

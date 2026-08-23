"""有界修复 v0（B3）：Finding → 修复任务，经 B2 任务机执行，同指纹熔断。

修复智能在脊柱之外：人或模型插件在契约内完成语义修复（手册 5.6）；
本模块只提供有界框架——契约、预算、指纹熔断、完成门复用。
git worktree 隔离留给存在自动修复者的那一天（ROADMAP 记录暂缓理由）。
"""
from __future__ import annotations

from pathlib import Path

from .audit import run_audit
from .ledger import Ledger
from .model import Finding
from .registry import Registry
from .task import Contract, TaskRecord, TaskStatus, TaskStore


class RepairError(Exception):
    pass


TERMINAL_FAILED = {TaskStatus.failed_unverified, TaskStatus.blocked}


def open_repair(
    root: Path,
    finding_id: str,
    allowed_writes: list[str],
    sensors: list,
    detectors: list,
) -> TaskRecord:
    root = Path(root)
    findings = Ledger(root / ".sopcontrol" / "evidence" / "ledger.jsonl").load_findings()
    finding = next((f for f in findings if f.finding_id == finding_id), None)
    if finding is None:
        raise RepairError(f"未找到 finding {finding_id}；先运行 sopctl audit 产生可修复的断口")
    if not finding.rule_id:
        raise RepairError(f"finding {finding_id} 不关联规则，无法定义完成标准，不开修复任务")

    rules = {r.rule_id: r for r in Registry(root / ".sopcontrol" / "rules" / "registry.yaml").load()}
    rule = rules.get(finding.rule_id)
    if rule is None:
        raise RepairError(f"finding 引用的规则 {finding.rule_id} 不在注册表")

    store = TaskStore(root)
    same = [t for t in store.list_all() if t.contract.repairs_fingerprint == finding.fingerprint]
    for t in same:
        if t.status in TERMINAL_FAILED:
            raise RepairError(
                f"同指纹修复已失败（{t.task_id} → {t.status.value}）：熔断转人工，"
                f"不再自动开修复（手册 5.8 有界修复）"
            )
        raise RepairError(
            f"该断口已有进行中的修复任务 {t.task_id}（{t.status.value}）；先完成或终结它"
        )

    report = run_audit(root, sensors, detectors, persist=False)
    verdict = next((v for v in report.verdicts if v.rule_id == rule.rule_id), None)
    if verdict is not None and verdict.status == "pass":
        raise RepairError(f"规则 {rule.rule_id} 当前判定 pass，无需修复")

    task = TaskRecord(
        task_id=store.next_task_id(),
        contract=Contract(
            objective=f"修复断口 {finding.pattern_id}（规则 {rule.rule_id}）：{finding.summary}",
            allowed_writes=list(allowed_writes),
            required_rules=[rule.rule_id],
            repairs_fingerprint=finding.fingerprint,
        ),
    )
    store.save(task)
    return task


def list_repairs(root: Path) -> list[TaskRecord]:
    return [t for t in TaskStore(root).list_all() if t.contract.repairs_fingerprint]

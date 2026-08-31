"""有界修复（B3）：Finding → 修复任务；自动修复者在 worktree 内改文件后合并回主树。

脊柱不内嵌 LLM：apply 通过外部 harness CLI（默认 opencode）执行语义修复。
"""
from __future__ import annotations

from pathlib import Path

from .audit import run_audit
from .ledger import Ledger
from .model import Finding
from .registry import Registry
from .task import Contract, TaskRecord, TaskStatus, TaskStore, path_allowed
from .worktree import (
    WorktreeError,
    copy_paths_to_main,
    create_repair_worktree,
    list_changed_files,
    remove_repair_worktree,
    resolves_inside,
    worktree_path,
)


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

    from .model import active_rules

    all_rules = Registry(root / ".sopcontrol" / "rules" / "registry.yaml").load()
    rules = {rule.rule_id: rule for rule in active_rules(all_rules)}
    rule = rules.get(finding.rule_id)
    if rule is None:
        raise RepairError(
            f"finding 引用的规则 {finding.rule_id} 不存在或已永久退出，不能产生新的修复义务"
        )

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


def _repair_prompt(task: TaskRecord) -> str:
    allows = ", ".join(task.contract.allowed_writes) or "（无）"
    rules = ", ".join(task.contract.required_rules) or "（无）"
    return (
        f"你是有界修复执行者。目标：{task.contract.objective}\n"
        f"只允许修改这些路径前缀：{allows}\n"
        f"完成后规则 {rules} 应能判定 pass。\n"
        f"不要改 .sopcontrol/；不要扩大范围；做最小改动后停止。"
    )


def apply_repair(
    root: Path,
    task_id: str,
    *,
    harness: str = "opencode",
    runner=None,
    timeout: int = 300,
    keep_worktree: bool = False,
) -> dict:
    """在 worktree 中调用外部模型做最小修复，并把契约内改动合并回主树。

    runner(worktree_path, prompt) -> None 可注入（测试用）；默认 opencode run。
    """
    root = Path(root).resolve()
    store = TaskStore(root)
    task = store.load(task_id)
    if not task.contract.repairs_fingerprint:
        raise RepairError(f"{task_id} 不是修复任务（无 repairs_fingerprint）")
    if task.status not in (TaskStatus.contract_proposed, TaskStatus.executing, TaskStatus.repair_required):
        raise RepairError(f"任务状态 {task.status.value} 不可自动修复")

    try:
        work = create_repair_worktree(root, task_id)
    except WorktreeError as exc:
        raise RepairError(str(exc)) from exc

    prompt = _repair_prompt(task)
    try:
        if runner is not None:
            runner(work, prompt)
        elif harness == "opencode":
            from .evals import _run_logged

            code, out = _run_logged(["opencode", "run", prompt], work, timeout)
            if code == -1:
                raise RepairError(f"自动修复超时：{out[-200:]}")
        else:
            raise RepairError(f"暂不支持 harness={harness!r}（当前：opencode）")

        changed = list_changed_files(work)
        # 三层：契约范围（纯字符串）→ 控制器目录（大小写不敏感）→ symlink 解析后仍在树内。
        # 前两层拦不住 `src/link -> /etc` 这类逃逸，最后一层必须碰文件系统，只能在这里做。
        allowed = [
            p for p in changed
            if path_allowed(p, task.contract.allowed_writes)
            and resolves_inside(work, p)
        ]
        rejected = [p for p in changed if p not in allowed]
        copied = copy_paths_to_main(work, root, allowed)
    finally:
        if not keep_worktree:
            remove_repair_worktree(root, task_id)

    return {
        "task_id": task_id,
        "worktree": str(worktree_path(root, task_id)),
        "changed": changed,
        "copied": copied,
        "rejected_out_of_contract": rejected,
        "prompt": prompt[:200],
    }

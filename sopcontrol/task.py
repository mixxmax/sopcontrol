"""任务状态机与完成门（B2 快回路）。

设计（DESIGN.md §10）：任务契约是三原子的组合，不新增第四种真相；
迁移判定是纯函数（无 I/O），状态 I/O 由 TaskStore 承担；
revision 防旧上下文覆盖新状态；blocked/failed_unverified 为终态。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from .model import utcnow


class TaskStatus(str, Enum):
    contract_proposed = "contract_proposed"
    executing = "executing"
    verification_pending = "verification_pending"
    verified = "verified"
    repair_required = "repair_required"
    blocked = "blocked"
    failed_unverified = "failed_unverified"
    delivered = "delivered"


TASK_TRANSITIONS: dict[TaskStatus, frozenset] = {
    TaskStatus.contract_proposed: frozenset({TaskStatus.executing}),
    TaskStatus.executing: frozenset({TaskStatus.verification_pending}),
    TaskStatus.verification_pending: frozenset(
        {TaskStatus.verified, TaskStatus.repair_required, TaskStatus.blocked, TaskStatus.failed_unverified}
    ),
    TaskStatus.repair_required: frozenset(
        {TaskStatus.verification_pending, TaskStatus.failed_unverified, TaskStatus.blocked}
    ),
    TaskStatus.verified: frozenset({TaskStatus.delivered}),
    TaskStatus.blocked: frozenset(),
    TaskStatus.failed_unverified: frozenset(),
    TaskStatus.delivered: frozenset(),
}


class Contract(BaseModel):
    objective: str
    allowed_writes: list[str] = Field(default_factory=list)   # 路径前缀（目录或文件）
    required_rules: list[str] = Field(default_factory=list)   # 完成定义：这些规则 verdict==pass
    max_repairs: int = 2                                       # 手册 10.5：默认两轮，超出转终态
    repairs_fingerprint: Optional[str] = None                  # 非 None = 修复任务，绑定 Finding 指纹


class EnvelopeRecord(BaseModel):
    """每次迁移的 Policy Envelope：可回放、可审计。"""
    at: datetime = Field(default_factory=utcnow)
    action: str
    from_status: TaskStatus
    to_status: Optional[TaskStatus] = None   # None = 迁移被拒绝，状态不变
    allowed: bool
    reason: str
    detail: dict = Field(default_factory=dict)


class TaskRecord(BaseModel):
    task_id: str
    contract: Contract
    status: TaskStatus = TaskStatus.contract_proposed
    repair_count: int = 0
    changed_paths: list[str] = Field(default_factory=list)
    revision: int = 1
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    history: list[EnvelopeRecord] = Field(default_factory=list)


class TransitionDecision(BaseModel):
    allowed: bool
    to_status: Optional[TaskStatus]
    reason: str
    next_action: str
    repair_count: int = 0


def normalize_relpath(path: str) -> str:
    """规范化相对路径；绝对路径与上跳直接拒绝（返回原值由调用方判定非法）。"""
    p = PurePosixPath(path.strip())
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"非法路径 {path!r}：只接受仓库内相对路径，不允许绝对路径或 '..'")
    return str(p)


def path_allowed(changed: str, allowed_writes: list[str]) -> bool:
    try:
        norm = normalize_relpath(changed)
    except ValueError:
        return False
    for allow in allowed_writes:
        try:
            a = normalize_relpath(allow)
        except ValueError:
            continue
        if norm == a or norm.startswith(a.rstrip("/") + "/"):
            return True
    return False


def evaluate_transition(
    task: TaskRecord,
    action: str,
    *,
    changed_paths: Optional[list[str]] = None,
    rule_verdicts: Optional[dict[str, str]] = None,
    known_rule_ids: Optional[set[str]] = None,
    ledger_tampered: bool = False,
) -> TransitionDecision:
    """纯函数迁移门：无 I/O。所有拒绝必须给出理由与下一步（手册 11.2）。"""
    status = task.status

    if action == "accept":
        if status != TaskStatus.contract_proposed:
            return _reject(f"任务处于 {status.value}，只有 contract_proposed 可接受")
        contract = task.contract
        problems = []
        if not contract.objective.strip():
            problems.append("objective 为空")
        if not contract.allowed_writes:
            problems.append("allowed_writes 为空（无写入范围的任务无法做范围检查）")
        if not contract.required_rules:
            problems.append("required_rules 为空（无可验证完成定义的任务不得接受——防假完成）")
        unknown = [r for r in contract.required_rules if known_rule_ids is not None and r not in known_rule_ids]
        if unknown:
            problems.append(f"引用了不存在的规则: {', '.join(unknown)}")
        if problems:
            return _reject("契约不完整: " + "；".join(problems) + "。修复后重新 open 或修改契约")
        return TransitionDecision(
            allowed=True, to_status=TaskStatus.executing,
            reason="契约完整：目标、写入范围与可验证完成定义齐备",
            next_action="执行变更后 task submit 提交改动路径",
        )

    if action == "submit":
        if status not in (TaskStatus.executing, TaskStatus.repair_required):
            return _reject(f"任务处于 {status.value}，不可提交")
        paths = changed_paths or []
        if not paths:
            return _reject("submit 需要至少一个 --changed 路径（完成门依据改动范围审计）")
        illegal = [p for p in paths if not path_allowed(p, task.contract.allowed_writes)]
        if illegal:
            return TransitionDecision(
                allowed=False, to_status=None,
                reason=f"范围走私被拒绝：{', '.join(illegal)} 不在契约的 allowed_writes 内；"
                       f"扩大范围需人工重新确认契约（14.1 场景9）",
                next_action="只提交契约内路径，或经人工确认后修改 allowed_writes",
            )
        return TransitionDecision(
            allowed=True, to_status=TaskStatus.verification_pending,
            reason=f"改动 {len(paths)} 个路径，全部在写入范围内",
            next_action="运行 task verify 由控制器独立审计",
        )

    if action == "verify":
        if status != TaskStatus.verification_pending:
            return _reject(f"任务处于 {status.value}，无可验证的提交")
        if ledger_tampered:
            return TransitionDecision(
                allowed=True, to_status=TaskStatus.blocked, repair_count=task.repair_count,
                reason="证据账本被篡改或损坏：信任根受损，转人工（12.2 fail-closed）",
                next_action="sopctl doctor 复核账本，人工裁决后重建任务",
            )
        verdicts = rule_verdicts or {}
        for rule_id in task.contract.required_rules:
            if rule_id not in verdicts:
                return TransitionDecision(
                    allowed=True, to_status=TaskStatus.blocked, repair_count=task.repair_count,
                    reason=f"规则 {rule_id} 无判定结果（规则缺失或审计失败）：无法验证即阻断，不猜",
                    next_action="检查规则注册表与审计日志（sopctl audit）",
                )
        # 完成门只裁决本任务契约声明的规则；全项目口径属于终点门（sopctl gate）
        fails = [r for r in task.contract.required_rules if verdicts[r] == "fail"]
        gaps = [r for r in task.contract.required_rules if verdicts[r] in ("gap", "unknown")]
        if fails:
            return TransitionDecision(
                allowed=True, to_status=TaskStatus.blocked, repair_count=task.repair_count,
                reason=f"策略违反：规则 {', '.join(fails)} 判定为 fail（存在绕过/违规），模型不得自行绕过（14.1 场景5）",
                next_action="人工裁决 fail 规则；修复绕过后重新走任务流程",
            )
        if gaps:
            new_count = task.repair_count + 1
            if new_count > task.contract.max_repairs:
                return TransitionDecision(
                    allowed=True, to_status=TaskStatus.failed_unverified, repair_count=new_count,
                    reason=f"修复预算耗尽（{task.repair_count} 轮未收敛，规则 {', '.join(gaps)} 仍为 gap）——转终态（14.1 场景11 熔断）",
                    next_action="人工介入分析 gap 根因后另开任务",
                )
            return TransitionDecision(
                allowed=True, to_status=TaskStatus.repair_required, repair_count=new_count,
                reason=f"第 {new_count} 轮修复：规则 {', '.join(gaps)} 未达标（gap/unknown）",
                next_action="最小范围修复后 task submit 重新提交（不重做整个任务）",
            )
        return TransitionDecision(
            allowed=True, to_status=TaskStatus.verified, repair_count=task.repair_count,
            reason=f"完成门通过：全部必需规则 [{', '.join(task.contract.required_rules)}] 判定 pass（E3 独立审计）",
            next_action="task deliver 交付",
        )

    if action == "deliver":
        if status == TaskStatus.delivered:
            return _reject("任务已交付")
        if status != TaskStatus.verified:
            return _reject(f"任务处于 {status.value}；只有 verified 可交付——完成门未过不得宣称交付（防假完成）")
        return TransitionDecision(
            allowed=True, to_status=TaskStatus.delivered,
            reason="完成门已独立验证，允许交付",
            next_action="无",
        )

    return _reject(f"未知动作 {action!r}：合法动作是 accept / submit / verify / deliver")


def _reject(reason: str) -> TransitionDecision:
    return TransitionDecision(allowed=False, to_status=None, reason=reason, next_action="sopctl task show 查看当前状态与契约")


class TaskStore:
    """任务文件存储：.sopcontrol/tasks/TASK-xxxx.yaml；revision 冲突即拒绝写。"""

    def __init__(self, root: Path):
        self.dir = Path(root) / ".sopcontrol" / "tasks"

    def _path(self, task_id: str) -> Path:
        return self.dir / f"{task_id}.yaml"

    def next_task_id(self) -> str:
        self.dir.mkdir(parents=True, exist_ok=True)
        nums = []
        for f in self.dir.glob("TASK-*.yaml"):
            try:
                nums.append(int(f.stem.split("-")[1]))
            except (IndexError, ValueError):
                continue
        return f"TASK-{(max(nums) + 1) if nums else 1:04d}"

    def save(self, task: TaskRecord, expected_revision: Optional[int] = None) -> None:
        path = self._path(task.task_id)
        if path.exists():
            current = self.load(task.task_id)
            base = expected_revision if expected_revision is not None else task.revision - 1
            if current.revision != base:
                raise RuntimeError(
                    f"revision 冲突：磁盘上 {task.task_id} 已是 r{current.revision}，"
                    f"本次写入基于 r{base}（旧上下文不得覆盖新状态，手册 5.5）"
                )
        self.dir.mkdir(parents=True, exist_ok=True)
        task.updated_at = utcnow()
        path.write_text(
            yaml.safe_dump(task.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def load(self, task_id: str) -> TaskRecord:
        path = self._path(task_id)
        if not path.exists():
            known = ", ".join(p.stem for p in sorted(self.dir.glob("TASK-*.yaml"))) or "（无任务）"
            raise KeyError(f"未找到任务 {task_id}；现有: {known}")
        return TaskRecord.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    def list_all(self) -> list[TaskRecord]:
        if not self.dir.exists():
            return []
        return [self.load(p.stem) for p in sorted(self.dir.glob("TASK-*.yaml"))]

    def apply(self, task: TaskRecord, decision: TransitionDecision, action: str, changed_paths: Optional[list[str]] = None) -> TaskRecord:
        """把判定应用到任务记录：迁移状态或仅记录被拒绝的 envelope。"""
        envelope = EnvelopeRecord(
            action=action,
            from_status=task.status,
            to_status=decision.to_status,
            allowed=decision.allowed,
            reason=decision.reason,
            detail={"next_action": decision.next_action},
        )
        task.history.append(envelope)
        if decision.allowed and decision.to_status is not None:
            if decision.to_status not in TASK_TRANSITIONS[task.status]:
                raise RuntimeError(
                    f"非法任务迁移 {task.status.value} → {decision.to_status.value}"
                )
            task.status = decision.to_status
            task.repair_count = decision.repair_count if action == "verify" else task.repair_count
            if action == "submit":
                task.changed_paths = list(changed_paths or [])
        task.revision += 1
        self.save(task)
        return task

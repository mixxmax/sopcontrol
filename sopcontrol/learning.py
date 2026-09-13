"""P0-B：自动学习统一数据模型（手册 §4）。

地位：纯数据层。只表达“发生过什么”，不判定、不写 Registry——
Registry 写入永远走现有 `dynamic_sop.confirm/compile` 正规链。
未知字段策略与项目现有模型一致：严格拒绝（extra=forbid）。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .model import content_hash, utcnow

_STRICT = ConfigDict(extra="forbid")

# §4.4：提案状态与规则状态必须分开——提案是“待人定的建议”，规则是权威。
ProposalStatus = Literal["proposed", "confirmed", "deferred", "rejected", "superseded"]
ProposalRoute = Literal["control", "document", "both", "once_only", "defer", "reject"]
EventKind = Literal["utterance", "correction", "tool_call", "task_boundary", "decay"]


class LearningEvent(BaseModel):
    """§4.1：只表达发生过的事情。禁止在事件阶段写入“Rule 已生效”。"""
    model_config = _STRICT

    event_id: str = ""
    kind: EventKind = "utterance"
    # 引用（会话/消息/工具调用/任务），不解释
    session_id: str = ""
    task_id: str = ""
    tool_call_ref: str = ""
    message_ref: str = ""
    # 内容（原文裁剪，脱敏在聚合层做）
    text: str = ""
    scope: dict[str, str] = Field(default_factory=dict)  # product/action/phase
    observed_at: datetime = Field(default_factory=utcnow)

    def model_post_init(self, _) -> None:
        if not self.event_id:
            self.event_id = "lev-" + content_hash(
                {"kind": self.kind, "text": self.text,
                 "task": self.task_id, "tool": self.tool_call_ref})[:20]


class LearningWindow(BaseModel):
    """§4.2：一次规则回顾的范围。按任务/阶段切分，不按任意时长截断。"""
    model_config = _STRICT

    window_id: str = ""
    task_id: str = ""
    phase: str = ""
    product: str = ""
    session_id: str = ""
    opened_at: datetime = Field(default_factory=utcnow)
    closed_at: Optional[datetime] = None
    event_ids: list[str] = Field(default_factory=list)

    def model_post_init(self, _) -> None:
        if not self.window_id:
            self.window_id = "lwin-" + content_hash(
                {"task": self.task_id, "phase": self.phase,
                 "session": self.session_id})[:20]

    @property
    def is_open(self) -> bool:
        return self.closed_at is None


class EvidenceBundle(BaseModel):
    """交给 Distiller 的证据包：窗口内事件 + 归并主题（P1-A 填充，P0 只定形）。"""
    model_config = _STRICT

    bundle_id: str = ""
    window_id: str = ""
    events: list[LearningEvent] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    pruned_count: int = 0  # 脱敏/裁剪掉的数量（如实计数）
    built_at: datetime = Field(default_factory=utcnow)

    def model_post_init(self, _) -> None:
        if not self.bundle_id:
            self.bundle_id = "levb-" + content_hash(
                {"window": self.window_id,
                 "events": [e.event_id for e in self.events]})[:20]


class LearningProposal(BaseModel):
    """§4.3：归并后的规则建议。0 到 3 条/窗口；生效范围 + 例外 + 非目标必填。"""
    model_config = _STRICT

    proposal_id: str = ""
    window_id: str = ""
    statement: str
    scope_summary: str = ""          # 适用任务/动作/阶段
    exceptions: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    rule_class: str = "dynamic_sop"  # constitution/dynamic_sop/natural_logic
    route: ProposalRoute = "defer"
    status: ProposalStatus = "proposed"
    evidence_refs: list[str] = Field(default_factory=list)
    proposed_at: datetime = Field(default_factory=utcnow)
    decided_at: Optional[datetime] = None

    def model_post_init(self, _) -> None:
        if not self.proposal_id:
            self.proposal_id = "lprop-" + content_hash(
                {"statement": self.statement, "window": self.window_id})[:20]


class ProposalDecision(BaseModel):
    """§4.4：人对提案的决定。决定只改提案状态；规则生效另走正规链。"""
    model_config = _STRICT

    proposal_id: str
    route: ProposalRoute
    actor: str = "user"
    note: str = ""
    decided_at: datetime = Field(default_factory=utcnow)


def event_from_observation(obs: Any, *, task_id: str = "",
                           session_id: str = "") -> LearningEvent:
    """P0-B：UtteranceObservation → LearningEvent（只搬运，不解释）。"""
    return LearningEvent(
        kind="utterance",
        session_id=session_id,
        task_id=task_id,
        message_ref=getattr(obs, "observation_id", ""),
        text=str(getattr(obs, "exact_quote", "")),
        scope={str(k): str(v) for k, v in
               (getattr(obs, "context", None) or {}).items()},
    )


def proposal_input_from_candidate(record: Any) -> dict[str, Any]:
    """P0-B：CandidateRecord → 提案输入（字典形态，不建规则，不写盘）。"""
    sources = getattr(record, "sources", None) or []
    return {
        "statement": str(getattr(record, "statement", "")),
        "scope_guess": str(getattr(record, "scope_guess", "project")),
        "suggested_modality": str(getattr(record, "suggested_modality", "MUST")),
        "frequency": int(getattr(record, "frequency", 0) or 0),
        "priority": str(getattr(record, "priority", "low")),
        "source_refs": [str(getattr(s, "ref", "")) for s in sources],
        "explicit_once_only": bool(getattr(record, "explicit_once_only", False)),
    }


def open_window(*, task_id: str = "", phase: str = "", product: str = "",
                session_id: str = "") -> LearningWindow:
    return LearningWindow(task_id=task_id, phase=phase, product=product,
                          session_id=session_id)


def close_window(window: LearningWindow) -> LearningWindow:
    out = window.model_copy()
    out.closed_at = utcnow()
    return out


def load_legacy_candidates(root: Path | str) -> list[Any]:
    """P0-B：旧候选可加载（只读，供转换）。"""
    from .candidate import CandidateStore
    return CandidateStore(Path(root)).load()


def load_legacy_rules(root: Path | str) -> list[Any]:
    """P0-B：旧规则可加载（只读，供关联）。"""
    from .registry import Registry
    return Registry(Path(root) / ".sopcontrol" / "rules" / "registry.yaml").load()

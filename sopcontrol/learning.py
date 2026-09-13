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
    conflicts: list[str] = Field(default_factory=list)  # P1-A：同组对立表达
    related_rule_ids: list[str] = Field(default_factory=list)  # P1-A：关联的现存规则
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


# ---------------------------------------------------------------------------
# P1-A：窗口级聚合器（纯函数）
# ---------------------------------------------------------------------------

_OPPOSE_MARKERS = (("必须", "不得"), ("必须", "禁止"), ("必须", "不要"),
                   ("应该", "不应该"), ("要", "别"))


def _loose(text: str) -> str:
    import re
    import unicodedata
    t = unicodedata.normalize("NFKC", str(text)).casefold()
    t = "".join(ch for ch in t if not unicodedata.category(ch).startswith("P"))
    return re.sub(r"\s+", " ", t).strip()


def _desensitize(text: str, limit: int = 200) -> str:
    import re
    t = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<email>", text)
    t = re.sub(r"sk-\S+|(?:secret|token|password)\s*[:=]\s*\S+", "<redacted>", t,
               flags=re.IGNORECASE)
    return t[:limit]


def aggregate_window(events: list[LearningEvent], window: LearningWindow,
                     *, existing_rules: list[Any] | None = None) -> EvidenceBundle:
    """P1-A：收集→脱敏裁剪→按主题/动作/目标归并→同义去重→冲突检测→关联旧规则。

    分散的多条纠正归并为一个主题（不是每条原话复制成候选）。
    """
    in_window = [e for e in events
                 if (not window.event_ids or e.event_id in set(window.event_ids))
                 and (not window.task_id or e.task_id in ("", window.task_id))]
    kept: list[LearningEvent] = []
    pruned = 0
    for e in in_window:
        if not e.text.strip():
            pruned += 1
            continue
        kept.append(e.model_copy(update={"text": _desensitize(e.text)}))
    groups: dict[tuple, list[LearningEvent]] = {}
    for e in kept:
        key = (e.scope.get("product", ""), e.scope.get("action", ""),
               e.scope.get("phase", ""))
        groups.setdefault(key, []).append(e)
    topics: list[str] = []
    conflicts: list[str] = []
    for key, members in sorted(groups.items()):
        seen: dict[str, LearningEvent] = {}
        for m in members:
            seen.setdefault(_loose(m.text), m)
        uniq = sorted(seen, key=len)
        topics.append(" / ".join(u[:60] for u in uniq[:3]))
        texts = " ".join(seen)
        for must, must_not in _OPPOSE_MARKERS:
            if must in texts and must_not in texts:
                conflicts.append(f"{'/'.join(k for k in key if k) or '通用'}: "
                                 f"“{must}”与“{must_not}”对立")
    related: list[str] = []
    for rule in existing_rules or []:
        rstmt = _loose(str(getattr(rule, "statement", "")))
        if rstmt and any(rstmt[:24] in _loose(e.text) or _loose(e.text)[:24] in rstmt
                         for e in kept):
            related.append(str(getattr(rule, "rule_id", "")))
    return EvidenceBundle(window_id=window.window_id, events=kept, topics=topics,
                          conflicts=conflicts, related_rule_ids=sorted(set(related)),
                          pruned_count=pruned)


# ---------------------------------------------------------------------------
# P1-B：确定性触发器（纯函数；阈值集中一处）
# ---------------------------------------------------------------------------

_HIGH_SIGNALS = ("以后必须", "以后不得", "永久", "always must", "must never")
_MID_SIGNALS = ("纠正", "更正", "应该", "不应该", "不要", "改为", "必须", "范围")
_LOW_SIGNALS = ("也许", "可能", "考虑", "顺便")


class TriggerConfig(BaseModel):
    """P1-B：全部阈值集中在此，行为可测。"""
    model_config = _STRICT

    repeat_escalation: int = 2          # 同一主题出现 N 次→升级
    high_immediate: bool = True         # 高价值信号可在自然边界立即提炼
    once_only_never_permanent: bool = True
    dedupe_popups: bool = True          # 同一指纹不重复弹窗


class TriggerDecision(BaseModel):
    model_config = _STRICT

    fire: bool = False
    level: str = "none"  # none/defer/suggest/immediate
    reason: str = ""
    fingerprint: str = ""
    forces_permanent: bool = False  # 恒 False：触发器永不强制（§5.4）


def _signal_level(text: str) -> str:
    t = str(text)
    if any(s in t for s in _HIGH_SIGNALS):
        return "high"
    if any(s in t for s in _MID_SIGNALS):
        return "mid"
    if any(s in t for s in _LOW_SIGNALS):
        return "low"
    return "none"


def evaluate_trigger(bundle: EvidenceBundle, *,
                     config: TriggerConfig | None = None,
                     seen_fingerprints: set[str] | None = None,
                     has_conflict: bool = False) -> TriggerDecision:
    """P1-B：普通聊天不触发；一次纠正延后；重复升级；同指纹不重弹；冲突不强制。"""
    config = config or TriggerConfig()
    seen = seen_fingerprints or set()
    texts = " ".join(e.text for e in bundle.events)
    if not texts.strip():
        return TriggerDecision(fire=False, level="none", reason="空窗口")
    if config.once_only_never_permanent and all(
            "仅本次" in e.text or "只针对这次" in e.text for e in bundle.events):
        return TriggerDecision(fire=False, level="none", reason="仅本次不进入永久")
    level = _signal_level(texts)
    if level == "none":
        return TriggerDecision(fire=False, level="none", reason="普通聊天无信号")
    if has_conflict or bundle.conflicts:
        fp = "trig-" + content_hash({"w": bundle.window_id, "t": "conflict"})[:16]
        return TriggerDecision(fire=True, level="suggest",
                               reason="冲突提案只建议，不强制", fingerprint=fp,
                               forces_permanent=False)
    reps = max((len(bundle.topics), 1))
    count = len(bundle.events)
    fp = "trig-" + content_hash(
        {"w": bundle.window_id, "topics": sorted(bundle.topics)})[:16]
    if config.dedupe_popups and fp in seen:
        return TriggerDecision(fire=False, level="none",
                               reason="同一指纹已提醒过", fingerprint=fp)
    if level == "high" and config.high_immediate:
        return TriggerDecision(fire=True, level="immediate",
                               reason="高价值信号", fingerprint=fp)
    if level == "mid" and count >= config.repeat_escalation:
        return TriggerDecision(fire=True, level="suggest",
                               reason=f"重复纠正升级（{count} 次）", fingerprint=fp)
    return TriggerDecision(fire=False, level="defer",
                           reason="一次纠正延后到阶段边界", fingerprint=fp)

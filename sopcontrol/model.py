"""三个原子记录：Rule / Evidence / Finding / Verdict。

宪法属性（见 tests/constitution）：
- 判定永远携带 rule_ids + reason + next_action（可解释性）；
- Evidence 自带 valid_until 与 input_hash（复查是账本的常驻行为，Haft 教训）；
- 记录 id 内容寻址，且不含时间戳字段——同一现场重复审计产生同一 id，账本幂等。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class Modality(str, Enum):
    MUST = "MUST"
    MUST_NOT = "MUST_NOT"
    SHOULD = "SHOULD"
    MAY = "MAY"


class RuleStatus(str, Enum):
    observed = "observed"
    proposed = "proposed"
    clarified = "clarified"
    accepted = "accepted"
    rejected = "rejected"
    compiled = "compiled"
    activated = "activated"
    monitored = "monitored"
    superseded = "superseded"
    deprecated = "deprecated"


# 手册 5.3 的显式生命周期；非法迁移由 registry 拒绝并说明原因。
ALLOWED_TRANSITIONS: dict[RuleStatus, frozenset] = {
    RuleStatus.observed: frozenset({RuleStatus.proposed, RuleStatus.rejected}),
    RuleStatus.proposed: frozenset({RuleStatus.clarified, RuleStatus.accepted, RuleStatus.rejected}),
    RuleStatus.clarified: frozenset({RuleStatus.proposed, RuleStatus.accepted, RuleStatus.rejected}),
    RuleStatus.accepted: frozenset({RuleStatus.compiled, RuleStatus.superseded, RuleStatus.deprecated}),
    RuleStatus.rejected: frozenset({RuleStatus.proposed}),
    RuleStatus.compiled: frozenset({RuleStatus.activated, RuleStatus.accepted, RuleStatus.superseded, RuleStatus.deprecated}),
    RuleStatus.activated: frozenset({RuleStatus.monitored, RuleStatus.superseded, RuleStatus.deprecated}),
    RuleStatus.monitored: frozenset({RuleStatus.superseded, RuleStatus.deprecated}),
    RuleStatus.superseded: frozenset(),
    RuleStatus.deprecated: frozenset(),
}


class Absorption(str, Enum):
    documented = "documented"              # 只存在于文档/对话，无任何代码消费者
    compiled_unwired = "compiled_unwired"  # 有编译产物但入口未消费（v0 保留枚举，尚无检测器）
    wired = "wired"                        # 有生产消费者，无回归证据
    wired_and_tested = "wired_and_tested"  # 消费者与回归证据齐备
    enforced = "enforced"                  # 手册 6.5 七条件齐备（trace + 确认书）


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class SourceRef(BaseModel):
    type: Literal["user_conversation", "document", "corpus", "constitution", "manual_seed"] = "manual_seed"
    ref: str
    observed_at: Optional[datetime] = None


class Rule(BaseModel):
    rule_id: str
    statement: str
    modality: Modality
    status: RuleStatus = RuleStatus.proposed
    scope: str = "project"
    owner: str = "user"
    risk: RiskLevel = RiskLevel.medium
    source: SourceRef
    consumer_markers: list[str] = Field(default_factory=list)
    legacy_markers: list[str] = Field(default_factory=list)  # 受控入口之外的旧路径符号；存活即可绕过
    state_markers: list[str] = Field(default_factory=list)   # 状态/字段符号；由 state_health 模式评估
    # 执行这条规则的运行时 guard id（harness.GUARD_IDS 之一）。声明了才可能拿到
    # trace 证据——手册 6.5 条件6 要的是「本轮这条规则真的被加载并决策过」，
    # 而「哪个拦截器算这条规则的执行者」只有规则作者知道，判定器不许猜。
    guard_ids: list[str] = Field(default_factory=list)
    # 确认书（手册 6.5 条件5+7，由 sopctl rule attest 写入，见 attest.py）。
    # source_hash 是 attest 当时源文档的内容 hash：文档一改就与现值不符，
    # 条件7 自动不成立，不需要谁记得来撤销 enforced。
    source_hash: str = ""
    bypass_note: str = ""            # 「这条规则能被怎么绕过」——分析结论，无法自动推导
    attested_by: str = ""
    attested_at: Optional[datetime] = None
    supersedes: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    accepted_at: Optional[datetime] = None

    @field_validator("rule_id")
    @classmethod
    def _rule_id_shape(cls, v: str) -> str:
        if not v or not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError("rule_id 只允许字母、数字、'-'、'_'，例如 PUSH-001")
        return v


class Evidence(BaseModel):
    evidence_id: str = ""
    kind: str                      # 例如 "code_scan.identifiers" / "doc_scan.must_statement"
    subject: str                   # 相对路径或对象标识
    observed: Any = None           # 传感器观测载荷
    observer: str                  # 传感器插件 id
    level: int = 3                 # 手册 4.3 的 E0–E4；控制器读文件为 E3
    input_hash: str                # 被观测对象内容的 hash，输入变化即暴露 stale
    observed_at: datetime = Field(default_factory=utcnow)
    valid_until: Optional[datetime] = None

    def model_post_init(self, _) -> None:
        if not self.evidence_id:
            self.evidence_id = self.compute_id()

    def compute_id(self) -> str:
        payload = self.model_dump(exclude={"evidence_id", "observed_at"}, mode="json")
        return "ev-" + content_hash(payload)

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        return self.valid_until is not None and (now or utcnow()) > self.valid_until


class Finding(BaseModel):
    finding_id: str = ""
    pattern_id: str                # 语料模式库中的通用模式 id
    rule_id: Optional[str] = None
    summary: str
    severity: Literal["info", "gap", "warn", "block"] = "gap"
    evidence_ids: list[str] = Field(default_factory=list)
    detector: str
    fingerprint: str = ""          # (pattern, rule) 指纹，供未来重复熔断使用
    detected_at: datetime = Field(default_factory=utcnow)

    def model_post_init(self, _) -> None:
        if not self.finding_id:
            self.finding_id = self.compute_id()
        if not self.fingerprint:
            self.fingerprint = content_hash({"pattern_id": self.pattern_id, "rule_id": self.rule_id})

    def compute_id(self) -> str:
        payload = self.model_dump(exclude={"finding_id", "detected_at", "fingerprint"}, mode="json")
        return "fn-" + content_hash(payload)


class Verdict(BaseModel):
    rule_id: str
    status: Literal["pass", "gap", "fail", "unknown"]
    absorption: Optional[Absorption] = None
    reason: str                    # 宪法：永远非空
    next_action: str               # 宪法：永远非空（pass 时为"无"）
    evidence_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    # 证据强度自曝（structural/lexical/mixed；None=无消费证据）：Go 规则和 Python
    # 规则的 pass 打印出来不能一个样——一个验证了代码结构，一个只搜到了字符串。
    grounding: Optional[str] = None

    def model_post_init(self, _) -> None:
        if not self.rule_ids:
            self.rule_ids = [self.rule_id]

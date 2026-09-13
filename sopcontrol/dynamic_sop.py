"""WP-A/B/C（终极手册 §2/§4）：动态 SOP 的捕获、确认、永久化与情境选择。

职责链（§4.2）：
  用户原话 observation → 确定性去重/聚合 → 候选（低打扰卡片）
  → 人工确认（记为长期/修改后记为长期/仅本次/不是规则）
  → 长期规则进入权威 Registry（rule_class=dynamic_sop，永不隐式过期）

不变量（§2.3/§4.4）：
- 已确认动态 SOP 只能经显式生命周期动作改变；无 TTL、无自动退休；
- "仅本次"指令不进入永久规则空间（会话级记录，进程结束即失效语义）；
- 模型建议（suggested=）只是候选素材，绝不直接产生权威规则；
- 未激活 ≠ 过期：选择器不匹配必须输出可解释的 not_applicable。
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from .candidate import CandidateSource, CandidateStore
from .model import (
    ActivationSelector,
    Flexibility,
    Rule,
    RuleStatus,
    SourceRef,
    content_hash,
    utcnow,
)

SCHEMA_VERSION = "1"

_STRICT = ConfigDict(extra="forbid")

# 显式临时表达（确定性识别；不依赖模型判断）
_ONCE_ONLY_MARKERS = (
    "仅本次", "只这次", "这次先", "就这一次", "仅此一次", "just this once",
    "this time only", "only for this run",
)

ConfirmDecision = "keep_longterm", "edit_keep_longterm", "once_only", "not_a_rule"


class UtteranceObservation(BaseModel):
    """用户原话 + 最小上下文（§4.2 第 1 步）。原话永不改写。"""
    model_config = _STRICT

    observation_id: str = ""
    exact_quote: str
    source_ref: str
    context: dict[str, str] = Field(default_factory=dict)  # action/phase/artifact_kind...
    suggested: dict[str, Any] = Field(default_factory=dict)  # 模型结构化建议（无权威）
    explicit_once_only: bool = False
    observed_at: datetime = Field(default_factory=utcnow)

    def model_post_init(self, _) -> None:
        if not self.observation_id:
            self.observation_id = "obs-" + content_hash(
                {"quote": self.exact_quote, "source_ref": self.source_ref})[:20]


def _dynamic_dir(root: Path) -> Path:
    d = Path(root) / ".sopcontrol-local" / "dynamic"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _atomic_write_jsonl(path: Path, records: list[dict]) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".dyn.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _observations_path(root: Path) -> Path:
    return _dynamic_dir(root) / "observations.jsonl"


def _once_only_path(root: Path) -> Path:
    return _dynamic_dir(root) / "once-only.jsonl"


def observe_utterance(
    root: Path | str, *, quote: str, source_ref: str,
    context: Optional[dict[str, str]] = None,
    suggested: Optional[dict[str, Any]] = None,
) -> tuple[UtteranceObservation, Any, bool]:
    """捕获用户原话 → 候选（去重）。返回 (observation, candidate_record, created)。

    确定性规则：所有纠正类表达都成为候选（不依赖"永久"关键词，§4.1/§12.2）；
    显式临时标记 → explicit_once_only（确认时只能进会话级记录）。
    """
    root = Path(root)
    quote = str(quote).strip()
    if not quote:
        raise ValueError("原话不能为空")
    if not source_ref.strip():
        raise ValueError("source_ref 不能为空（原话出处必须可追溯）")
    context = context or {}
    suggested = suggested or {}
    explicit_once = any(marker in quote.lower() or marker in quote
                        for marker in _ONCE_ONLY_MARKERS)
    obs = UtteranceObservation(exact_quote=quote, source_ref=source_ref,
                               context={str(k): str(v) for k, v in context.items()},
                               suggested=suggested, explicit_once_only=explicit_once)
    # 观察留痕（append 语义：原话记录不可变）
    path = _observations_path(root)
    records = _load_jsonl(path)
    records.append(obs.model_dump(mode="json"))
    _atomic_write_jsonl(path, records)
    # 候选聚合（指纹去重：同义重复不重复询问，§4.2 第 6 步）
    store = CandidateStore(root)
    normalized = " ".join(quote.split())
    candidate, created = store.upsert(
        kind="dynamic_sop",
        statement=normalized,
        scope_guess=str(context.get("product") or "project"),
        suggested_action="register_rule",
        suggested_modality="MUST",
        source=CandidateSource(source_type="user_utterance", ref=source_ref,
                               occurrence_id=obs.observation_id),
        note=("动态 SOP 候选：确认后永久保存（rule_class=dynamic_sop，无自动过期）；"
              "显式临时表达只会进入会话级记录"),
    )
    return obs, candidate, created


def list_dynamic_candidates(root: Path | str) -> list[dict[str, Any]]:
    root = Path(root)
    store = CandidateStore(root)
    out = []
    for record in store.load():
        if record.kind != "dynamic_sop":
            continue
        out.append(record.model_dump(mode="json"))
    return out


def confirm_candidate(
    root: Path | str, candidate_id: str, decision: str, *,
    edited_statement: str = "", actor: str = "user",
    activation: Optional[dict[str, list[str]]] = None,
    flexibility: Optional[dict[str, Any]] = None,
    rule_id: str = "",
) -> dict[str, Any]:
    """§4.2 第 5 步确认卡片。四种决定，权威性只来自人的显式选择。"""
    root = Path(root)
    store = CandidateStore(root)
    record = store.get(candidate_id)
    if record.kind != "dynamic_sop":
        raise ValueError(f"候选 {candidate_id} 不是动态 SOP 候选")
    if decision not in ConfirmDecision:
        raise ValueError(f"非法决定: {decision!r}（允许 {ConfirmDecision}）")
    statement = (edited_statement or record.statement).strip()

    if decision in ("keep_longterm", "edit_keep_longterm"):
        if not statement:
            raise ValueError("规则陈述不能为空")
        from .registry import Registry

        rid = rule_id or ("DR-" + content_hash({"statement": statement})[:8].upper())
        registry = Registry(root / ".sopcontrol" / "rules" / "registry.yaml")
        rules = registry.load()
        existing = next((r for r in rules if r.rule_id == rid), None)
        if existing is None:
            first_quote = record.sources[0].ref if record.sources else source_ref_of(record)
            rule = Rule(
                rule_id=rid, statement=statement,
                modality=record.suggested_modality,  # type: ignore[arg-type]
                status=RuleStatus.proposed, rule_class="dynamic_sop",
                owner=actor,
                source=SourceRef(type="user_conversation", ref=first_quote),
                activation=(ActivationSelector.model_validate(activation)
                            if activation else ActivationSelector()),
                flexibility=(Flexibility.model_validate(flexibility)
                             if flexibility else Flexibility()),
                tags=["dynamic_sop"],
            )
            registry.add(rule)
        else:
            rid = existing.rule_id
        # 生命周期：proposed → accepted → compiled（active 等价态）
        for target in (RuleStatus.accepted, RuleStatus.compiled):
            current = next(r for r in registry.load() if r.rule_id == rid)
            if current.status == target:
                continue
            registry.transition(rid, target)
        store.triage(candidate_id, "triaged")
        final = next(r for r in registry.load() if r.rule_id == rid)
        return {"decision": decision, "rule_id": rid,
                "rule_status": final.status.value, "permanent": True,
                "note": "动态 SOP 已永久保存；无 TTL，仅显式生命周期可改变"}
    if decision == "once_only":
        # 仅本次：会话级记录，绝不进入永久规则空间（§2.3）
        path = _once_only_path(root)
        records = _load_jsonl(path)
        records.append({"candidate_id": candidate_id, "statement": statement,
                        "recorded_at": utcnow().isoformat(), "actor": actor})
        _atomic_write_jsonl(path, records)
        store.triage(candidate_id, "triaged")
        return {"decision": decision, "permanent": False,
                "note": "仅本次：已记入会话级记录，不进入永久规则空间"}
    # not_a_rule
    store.triage(candidate_id, "rejected")
    return {"decision": decision, "permanent": False,
            "note": "已标记为非规则；相同原话不会重复生成候选"}


def source_ref_of(record: Any) -> str:
    return record.sources[0].ref if getattr(record, "sources", None) else "unknown"


def list_once_only(root: Path | str) -> list[dict[str, Any]]:
    return _load_jsonl(_once_only_path(Path(root)))


# ---------------------------------------------------------------------------
# WP-C：情境选择与可解释 not_applicable（§4.4）
# ---------------------------------------------------------------------------

_SELECTOR_FIELDS = ("products", "actions", "phases", "artifact_kinds", "actors")
_CONTEXT_KEYS = {"products": "product", "actions": "action", "phases": "phase",
                 "artifact_kinds": "artifact_kind", "actors": "actor"}


def select_rules(rules: list[Rule], context: dict[str, str]
                 ) -> tuple[list[Rule], list[dict[str, str]], list[dict[str, str]]]:
    """确定性情境选择。返回 (selected, not_applicable, unproven)。

    not_applicable 项带可解释原因（§4.4 要求的措辞形态）：
    "规则 DR-001 存在且 active；本次未选择，因为 action=jobs.scan，规则要求 action=materials.audit。"
    unproven 项（§5.2）：规则约束了某维度但本次上下文缺失——无法证明适用，
    不选择，也不伪装成 not_applicable：
    "规则 DR-001 未激活：无法证明 action，规则要求 action=materials.audit。"
    空选择器维度 = 不限。
    """
    selected: list[Rule] = []
    not_applicable: list[dict[str, str]] = []
    unproven: list[dict[str, str]] = []
    for rule in rules:
        if rule.status not in (RuleStatus.accepted, RuleStatus.compiled,
                               RuleStatus.activated, RuleStatus.monitored):
            continue  # 非权威态不参与选择（observed/proposed 不得硬拦截）
        mismatches: list[tuple[str, str, str]] = []
        missing: list[tuple[str, str]] = []
        for field in _SELECTOR_FIELDS:
            wanted = getattr(rule.activation, field)
            if not wanted:
                continue
            dim = _CONTEXT_KEYS[field]
            ctx_value = str(context.get(dim, ""))
            if not ctx_value:
                missing.append((dim, wanted[0]))
            elif ctx_value not in wanted:
                mismatches.append((dim, ctx_value, wanted[0]))
        if missing:
            dim, required = missing[0]
            unproven.append({
                "rule_id": rule.rule_id, "missing_field": dim,
                "reason": (f"规则 {rule.rule_id} 未激活：无法证明 {dim}，"
                           f"规则要求 {dim}={required}。"),
                "rule_class": rule.rule_class})
        elif mismatches:
            dim, actual, required = mismatches[0]
            reason = (f"规则 {rule.rule_id} 存在且 {rule.status.value}；"
                      f"本次未选择，因为 {dim}={actual}，规则要求 {dim}={required}。")
            not_applicable.append({"rule_id": rule.rule_id, "reason": reason,
                                   "rule_class": rule.rule_class})
        else:
            selected.append(rule)
    return selected, not_applicable, unproven

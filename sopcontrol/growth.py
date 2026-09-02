"""无感生长回路：发现自动推进，定型仍人控。

用户不必主动「养」规则；audit/gate 等既有路径会：
1. 记录本轮 finding 观察（打破 ledger 去重导致的「永远只有 1 次」）；
2. 聚合到 Candidate（达阈值才物化）；
3. 更新 growth-state，供投影给换模型看。

绝不自动 rule add / deprecate / 改代码——那些是人的编辑权。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field

from .candidate import CandidateStore, refresh_candidates
from .model import Finding, content_hash, utcnow

GROWTH_OBS_REL = ".sopcontrol/evidence/growth-observations.jsonl"
GROWTH_STATE_REL = ".sopcontrol/evidence/growth-state.yaml"
MAX_GROWTH_OBS = 2000


class GrowthObservation(BaseModel):
    occurrence_id: str = ""
    fingerprint: str
    pattern_id: str
    rule_id: str = ""
    summary: str = ""
    round_id: str = ""
    observed_at: datetime = Field(default_factory=utcnow)

    def model_post_init(self, _) -> None:
        if not self.occurrence_id:
            self.occurrence_id = "go-" + content_hash({
                "fingerprint": self.fingerprint,
                "round_id": self.round_id,
                "pattern_id": self.pattern_id,
                "rule_id": self.rule_id,
            })


class GrowthState(BaseModel):
    updated_at: datetime = Field(default_factory=utcnow)
    last_round_id: str = ""
    observation_count: int = 0
    candidates_observed: int = 0
    candidates_delete_entry: int = 0
    candidates_improve_entry: int = 0
    candidates_register_rule: int = 0
    last_materialized: int = 0
    pending_human: list[dict[str, str]] = Field(default_factory=list)
    note: str = (
        "发现与聚合无感自动；写入权威规则/删代码仍需人确认"
        "（candidate triage / rule add / repair）"
    )


def _obs_path(root: Path) -> Path:
    return Path(root) / GROWTH_OBS_REL


def _state_path(root: Path) -> Path:
    return Path(root) / GROWTH_STATE_REL


def record_finding_observations(
    root: Path,
    findings: list[Finding],
    *,
    round_id: Optional[str] = None,
    at: Optional[datetime] = None,
) -> int:
    """本轮 audit 见到的 finding 记为独立 occurrence（供候选达阈值）。"""
    if not findings:
        return 0
    root = Path(root)
    when = at or utcnow()
    rid = round_id or content_hash({"at": when.isoformat(), "n": len(findings)})
    path = _obs_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("a", encoding="utf-8") as fh:
        for finding in findings:
            obs = GrowthObservation(
                fingerprint=finding.fingerprint,
                pattern_id=finding.pattern_id,
                rule_id=finding.rule_id or "",
                summary=(finding.summary or "")[:160],
                round_id=rid,
                observed_at=when,
            )
            fh.write(obs.model_dump_json() + "\n")
            written += 1
    _maybe_compact_obs(path)
    return written


def load_growth_observations(root: Path) -> list[GrowthObservation]:
    path = _obs_path(root)
    if not path.exists():
        return []
    out: list[GrowthObservation] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(GrowthObservation.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return out


def _maybe_compact_obs(path: Path) -> None:
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return
    if len(lines) <= MAX_GROWTH_OBS + 100:
        return
    path.write_text("\n".join(lines[-MAX_GROWTH_OBS:]) + "\n", encoding="utf-8")


def write_growth_state(root: Path, state: GrowthState) -> None:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(state.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def load_growth_state(root: Path) -> GrowthState:
    path = _state_path(root)
    if not path.exists():
        return GrowthState()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return GrowthState.model_validate(data)
    except (OSError, ValueError, TypeError):
        return GrowthState()


def record_control_observation(
    root: Path,
    *,
    source: str,
    subject: str,
    rule_ids: list[str] | None = None,
    reason: str = "",
    at: Optional[datetime] = None,
) -> GrowthObservation:
    """轻量控制事件观察（harness/gate 拒绝），不跑全仓 audit。"""
    when = at or utcnow()
    rules = tuple(sorted(str(r) for r in (rule_ids or []) if r))
    pattern = (
        "control_harness_deny" if source == "harness" else "control_gate_block"
    )
    fingerprint = content_hash({
        "source": source,
        "subject": subject,
        "rule_ids": rules,
        "pattern": pattern,
    })
    obs = GrowthObservation(
        fingerprint=fingerprint,
        pattern_id=pattern,
        rule_id=",".join(rules) if rules else "",
        summary=(reason or f"{source} 拒绝 {subject}")[:160],
        round_id=content_hash({"at": when.isoformat(), "subject": subject}),
        observed_at=when,
    )
    # 每次拒绝独立 occurrence（用时间戳进 id）
    obs.occurrence_id = "go-" + content_hash({
        "fingerprint": fingerprint,
        "at": when.isoformat(),
        "subject": subject,
        "reason": (reason or "")[:80],
    })
    path = _obs_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(obs.model_dump_json() + "\n")
    _maybe_compact_obs(path)
    return obs


def ambient_grow_on_control_deny(
    root: Path,
    *,
    source: str,
    subject: str,
    rule_ids: list[str] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """harness/gate 拒绝后的无感生长：记账 + 聚合，不跑传感器。"""
    root = Path(root)
    obs = record_control_observation(
        root,
        source=source,
        subject=subject,
        rule_ids=rule_ids,
        reason=reason,
    )
    return ambient_grow(root, findings=None, round_id=obs.round_id)


def ambient_grow(
    root: Path,
    *,
    findings: Optional[list[Finding]] = None,
    round_id: Optional[str] = None,
    at: Optional[datetime] = None,
) -> dict[str, Any]:
    """无感生长一步：记观察 → 聚合候选 → 更新状态。不写 registry。"""
    from .chronicle import append_project_event

    root = Path(root)
    when = at or utcnow()
    rid = round_id or content_hash({"at": when.isoformat()})
    observed = 0
    if findings:
        observed = record_finding_observations(
            root, findings, round_id=rid, at=when,
        )
    result = refresh_candidates(root)
    store = CandidateStore(root)
    try:
        records = store.load()
    except (OSError, ValueError):
        records = []
    pending = [
        r for r in records
        if r.status == "observed"
    ]
    delete_n = sum(1 for r in pending if r.suggested_action == "delete_entry")
    improve_n = sum(1 for r in pending if r.suggested_action == "improve_entry")
    register_n = sum(1 for r in pending if r.suggested_action == "register_rule")
    pending_human = [
        {
            "candidate_id": r.candidate_id,
            "action": r.suggested_action,
            "statement": r.statement[:80],
        }
        for r in sorted(pending, key=lambda x: x.last_seen_at, reverse=True)[:8]
    ]
    state = GrowthState(
        updated_at=when,
        last_round_id=rid,
        observation_count=len(load_growth_observations(root)),
        candidates_observed=len(pending),
        candidates_delete_entry=delete_n,
        candidates_improve_entry=improve_n,
        candidates_register_rule=register_n,
        last_materialized=int(result.get("materialized") or 0),
        pending_human=pending_human,
    )
    write_growth_state(root, state)
    if state.last_materialized or observed:
        append_project_event(
            root,
            kind="growth.ambient",
            subject="growth",
            outcome="grew" if state.last_materialized else "observed",
            detail={
                "round_id": rid,
                "observations_written": observed,
                "materialized": state.last_materialized,
                "pending": len(pending),
                "delete_entry": delete_n,
            },
        )
    return {
        "round_id": rid,
        "observations_written": observed,
        "refresh": result,
        "state": state,
    }


def growth_lines(root: Path, *, limit: int = 5) -> list[str]:
    """投影用：无感生长现状；定型入口指向人。"""
    state = load_growth_state(root)
    if state.observation_count == 0 and state.candidates_observed == 0:
        return [
            "空间生长：尚无自动观察；日常 audit/gate 会无感积累。",
            "定型仍需人：`sopctl candidate triage` / `rule add`；修剪：`rule deprecate`。",
        ]
    lines = [
        f"空间生长（无感）：观察 {state.observation_count}；"
        f"待人定型候选 {state.candidates_observed}"
        f"（删入口 {state.candidates_delete_entry} / 改善入口 {state.candidates_improve_entry} / "
        f"登记规则 {state.candidates_register_rule}）",
        "发现已自动；写入权威或删代码仍需人确认——不是要你「推进发现」。",
    ]
    for item in state.pending_human[:limit]:
        lines.append(
            f"- [{item['action']}] {item['candidate_id']}: {item['statement']}"
        )
    if state.candidates_delete_entry:
        lines.append(
            "消歧优先：`sopctl candidate enact <CAND> --allow <旁路路径>` "
            "开有界删旁路任务；不要再加 MUST_NOT。"
        )
    lines.append("明细：`sopctl growth status`；全量候选：`sopctl candidate list`。")
    return lines

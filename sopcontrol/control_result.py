"""P0b：结构化控制结果 + 确定性状态门（§6.3 / §11）。

自由文本理由永不作为放行依据；not_run/unknown/out_of_scope/warn/block
按固定优先序判定；已消费 result_id 重放一律拒绝。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .control_profile import FrozenPlan

Outcome = Literal["pass", "pass_with_warnings", "block", "not_run", "unknown"]
FindingSeverity = Literal["blocking", "tolerated", "advisory", "out_of_scope"]
Independence = Literal["self_check", "separate_context", "separate_actor", "human_required"]

_INDEPENDENCE_RANK = {
    "self_check": 0,
    "separate_context": 1,
    "separate_actor": 2,
    "human_required": 3,
}


class ResultFinding(BaseModel):
    dimension: str
    severity: FindingSeverity
    summary: str = ""  # 人读摘要；判定只看 dimension+severity，不看文本


class ResultProducer(BaseModel):
    actor: str = ""
    independence: Independence = "self_check"


class ControlResult(BaseModel):
    result_id: str
    task_id: str = ""
    profile_id: str = ""
    profile_revision: int = 0
    effective_plan_digest: str = ""
    input_digest: str = ""
    baseline_digest: str = ""
    baseline_mode: str = ""  # 为空=结果未声明基线模式（不触发模式比对）
    checked_dimensions: list[str] = Field(default_factory=list)
    excluded_dimensions: list[str] = Field(default_factory=list)
    findings: list[ResultFinding] = Field(default_factory=list)
    repair_action: str = "none"
    rounds_used: int = 0
    stop_reason: str = ""
    producer: ResultProducer = Field(default_factory=ResultProducer)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Evaluation(BaseModel):
    outcome: Outcome
    reasons: list[str] = Field(default_factory=list)
    idempotency_key: str = ""
    result_id: str = ""


def idempotency_key(result: ControlResult) -> str:
    """§7.3：input + baseline + plan + 检查集合（同一键同策略只应有一个有效结果）。"""
    raw = json.dumps({
        "input": result.input_digest,
        "baseline": result.baseline_digest,
        "plan": result.effective_plan_digest,
        "checked": sorted(result.checked_dimensions),
    }, ensure_ascii=False, sort_keys=True)
    return "idem-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _consumed_dir(root: Path) -> Path:
    return Path(root) / ".sopcontrol-local" / "control-results" / "consumed"


def _key_index_dir(root: Path) -> Path:
    return Path(root) / ".sopcontrol-local" / "control-results" / "by-key"


def _reuse_log(root: Path) -> Path:
    return Path(root) / ".sopcontrol-local" / "control-results" / "reuse.jsonl"


def _is_consumed(root: Path, result_id: str) -> bool:
    return (_consumed_dir(root) / f"{result_id}.json").is_file()


def _mark_consumed(root: Path, result: ControlResult, outcome: Outcome,
                   reasons: list[str], key: str) -> None:
    d = _consumed_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{result.result_id}.json"
    if path.exists():
        return
    record = {
        "result_id": result.result_id, "outcome": outcome,
        "reasons": reasons, "idempotency_key": key,
        "rounds_used": result.rounds_used,
        "finding_severities": [f.severity for f in result.findings],
        "at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    kd = _key_index_dir(root)
    kd.mkdir(parents=True, exist_ok=True)
    kd.joinpath(f"{key}.json").write_text(
        json.dumps({**record, "cached_result_id": result.result_id},
                   ensure_ascii=False, indent=2), encoding="utf-8")


def _find_cached(root: Path, key: str) -> dict[str, Any] | None:
    """§7.3：同键已有有效结果即复用，不再消耗新的审计调用。"""
    path = _key_index_dir(root) / f"{key}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _log_reuse(root: Path, result: ControlResult, cached: dict[str, Any]) -> None:
    with open(_reuse_log(root), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "at": datetime.now(timezone.utc).isoformat(),
            "result_id": result.result_id,
            "reused_result_id": cached.get("cached_result_id") or cached.get("result_id"),
            "idempotency_key": cached.get("idempotency_key"),
            "outcome": cached.get("outcome"),
        }, ensure_ascii=False) + "\n")


def control_costs(root: Path | str) -> dict[str, Any]:
    """§10.6：成本来自用户明确要求的控制——审计/复用/修正/范围外/容忍/冲突阻断计数。"""
    root = Path(root)
    d = _consumed_dir(root)
    records: list[dict[str, Any]] = []
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                records.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    reuses = 0
    log = _reuse_log(root)
    if log.is_file():
        try:
            reuses = sum(1 for line in log.read_text(encoding="utf-8").splitlines() if line.strip())
        except OSError:
            reuses = 0
    outcomes: dict[str, int] = {}
    rounds = oos = tolerated = conflicts = 0
    for r in records:
        outcomes[r.get("outcome", "?")] = outcomes.get(r.get("outcome", "?"), 0) + 1
        rounds += int(r.get("rounds_used") or 0)
        for s in r.get("finding_severities") or []:
            if s == "out_of_scope":
                oos += 1
            if s == "tolerated":
                tolerated += 1
        if r.get("outcome") == "block" and any(
            ("参决" in x or "协议违规" in x or "digest 不一致" in x)
            for x in r.get("reasons") or []
        ):
            conflicts += 1
    return {
        "audits": len(records),
        "reuses": reuses,
        "repair_rounds_total": rounds,
        "out_of_scope_findings": oos,
        "tolerated_findings": tolerated,
        "profile_conflict_blocks": conflicts,
        "outcomes": outcomes,
    }


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        text = str(value or "")
        dt = datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None
        return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def evaluate_control_result(
    root: Path | str, result: ControlResult, frozen: FrozenPlan,
) -> Evaluation:
    """§6.3 确定性状态门。优先序固定：协议违规 > 缺失 > 阻断 > 警告 > 通过。"""
    root = Path(root)
    key = idempotency_key(result)
    reasons: list[str] = []

    def done(outcome: Outcome, why: str, *, consume: bool = True) -> Evaluation:
        reasons.append(why)
        if consume:
            _mark_consumed(root, result, outcome, reasons, key)
        return Evaluation(outcome=outcome, reasons=list(reasons),
                          idempotency_key=key, result_id=result.result_id)

    # §11.1：plan digest 必须一致——任务按一套规则开始，不能按另一套验收。
    if result.effective_plan_digest != frozen.digest:
        return done("unknown", "plan digest 不一致：结果不属于当前冻结计划", consume=False)
    if result.profile_id != frozen.profile_id:
        return done("unknown", "profile_id 与冻结计划不一致", consume=False)
    # §11.2：输入属于当前任务（scope 声明 task 时绑定）。
    scope_task = frozen.profile.scope.task
    if scope_task and result.task_id != scope_task:
        return done("unknown", f"结果 task {result.task_id!r} 不属于当前任务 {scope_task!r}",
                    consume=False)
    # §15.12：旧 revision 结果不可静默用于新策略。
    if result.profile_revision != frozen.revision:
        return done("unknown",
                    f"结果 revision r{result.profile_revision} 非当前 r{frozen.revision}：已失效",
                    consume=False)
    # §11.6：过期 profile 的结果不新鲜。
    expires = (frozen.profile.expires_at or "").strip()
    if expires:
        exp = _parse_time(expires)
        created = _parse_time(result.created_at)
        if exp is not None and created is not None and created > exp:
            return done("unknown", "结果晚于 profile 过期时间：已失效", consume=False)
    # §6.4：独立性不足的结果不能作为通过凭据。
    required_rank = _INDEPENDENCE_RANK[frozen.profile.baseline.independence_required]
    got_rank = _INDEPENDENCE_RANK[result.producer.independence]
    if got_rank < required_rank:
        return done("unknown",
                    f"独立性不足：要求 {frozen.profile.baseline.independence_required}，"
                    f"实际 {result.producer.independence}",
                    consume=False)
    # §12.3：重放已消费结果一律拒绝（不消费本次，防记录污染）。
    if _is_consumed(root, result.result_id):
        return done("unknown", f"结果 {result.result_id} 已消费：拒绝重放", consume=False)
    # §7.3/§10.2：同幂等键已有有效结果即复用（一次编译，多次执行）。
    cached = _find_cached(root, key)
    if cached is not None and cached.get("outcome") in (
        "pass", "pass_with_warnings", "block",
    ):
        _log_reuse(root, result, cached)
        reused = [f"复用幂等结果 {cached.get('cached_result_id')}（本次未消耗审计调用）"]
        reused.extend(str(x) for x in cached.get("reasons") or [])
        return Evaluation(outcome=cached["outcome"], reasons=reused,
                          idempotency_key=key, result_id=result.result_id)
    # §6.3：required 缺失 → not_run（未知不解释成通过）。
    required = set(frozen.profile.checks.required)
    checked = set(result.checked_dimensions)
    missing = sorted(required - checked)
    if missing:
        return done("not_run", f"required 检查缺失: {missing}")
    # §11.4：excluded 不得参决——出现在 checked 或带 blocking finding 即协议违规。
    excluded = set(frozen.profile.checks.excluded) | set(result.excluded_dimensions)
    intruding = sorted(excluded & checked)
    if intruding:
        return done("block", f"excluded 检查参决（出现在 checked 中）: {intruding}")
    for f in result.findings:
        if f.dimension in excluded and f.severity == "blocking":
            return done("block", f"excluded 维度 {f.dimension} 带 blocking finding：协议违规")
    # 修轮超预算 → 阻断（§7.1）。
    if result.rounds_used > frozen.profile.repair.max_rounds:
        return done("block",
                    f"修正轮数 {result.rounds_used} 超出上限 {frozen.profile.repair.max_rounds}")
    # §6.3：required 维度的 blocking → block；其余 out_of_scope 忽略（§4.3）。
    for f in result.findings:
        if f.severity == "blocking" and f.dimension in required:
            return done("block", f"blocking finding：{f.dimension}")
    # §6.3：仅 tolerated/advisory → pass_with_warnings；全净 → pass。
    decisive = [f for f in result.findings
                if f.severity in ("tolerated", "advisory") and f.dimension in required]
    if decisive or any(f.severity in ("tolerated", "advisory") for f in result.findings):
        return done("pass_with_warnings",
                    f"仅容忍/提示类发现 {len(decisive)} 项，不阻断")
    return done("pass", "required 检查完成，无阻断发现")

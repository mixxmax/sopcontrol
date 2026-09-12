"""P0a：Dynamic Control Profile——动态配置，静态执行。

任务开始前组合，冻结为 revision 后运行时只执行该 revision；
同输入同 revision 必得同 digest；冲突（required∩excluded、非法
baseline、越界预算）直接拒绝，不猜测。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

FORMAT_VERSION = "1"

CheckMode = Literal["block", "required", "report_only", "ignore"]
BaselineMode = Literal["authoritative", "verify", "reconcile"]

# 系统上限（手册 §12.1：预算缺失/为负/超上限必须覆盖；数值见 CLI help）。
SYSTEM_MAX_ROUNDS = 3
SYSTEM_MAX_AUDIT_CALLS = 10
SYSTEM_MAX_REPAIR_CALLS = 10


class ProfileError(ValueError):
    """profile 非法：缺字段、冲突或越界（理由进 message，不静默默认）。"""


class ProfileScope(BaseModel):
    project: str = "current-project"
    task: str = ""
    phase: str = ""


class ProfileChecks(BaseModel):
    required: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)
    modes: dict[str, CheckMode] = Field(default_factory=dict)


class ProfileBaseline(BaseModel):
    source_ref: str = ""
    generation_mode: BaselineMode = "authoritative"
    audit_mode: str = "compare_output_only"
    challenge_without_explicit_request: bool = False
    independence_required: str = "self_check"
    require_accept: bool = False  # True=基线接受纳入状态门（无接受记录不得通过）
    require_proven_independence: bool = False  # True=高独立性声明必须实证（无任务上下文也强制）


class ProfileRepair(BaseModel):
    policy: Literal["hard_errors_only"] = "hard_errors_only"
    max_rounds: int = 1
    recheck_unchanged_input: bool = False
    stop_after_pass: bool = True


StopWhen = Literal["pass", "pass_with_warnings", "max_rounds", "block"]

_MODE_RANK = {"ignore": 0, "report_only": 1, "required": 2, "block": 3}
_TOLERANCE_RANK = {"allowed": 0, "report_only": 1, "block": 2}


class ProfileBudget(BaseModel):
    max_audit_calls: int = 1
    max_repair_calls: int = 1


class ControlProfile(BaseModel):
    profile_id: str
    scope: ProfileScope = Field(default_factory=ProfileScope)
    checks: ProfileChecks = Field(default_factory=ProfileChecks)
    baseline: ProfileBaseline = Field(default_factory=ProfileBaseline)
    tolerance: dict[str, str] = Field(default_factory=dict)
    repair: ProfileRepair = Field(default_factory=ProfileRepair)
    budget: ProfileBudget = Field(default_factory=ProfileBudget)
    expires_at: str | None = None
    stop_when: list[StopWhen] = Field(default_factory=lambda: ["pass"])


class FrozenPlan(BaseModel):
    """冻结的 Effective Control Plan：revision 不可变，digest 绑定任务。"""

    profile_id: str
    revision: int
    digest: str
    profile: ControlProfile


def _profiles_dir(root: Path) -> Path:
    return Path(root) / ".sopcontrol-local" / "profiles"


class ComposedPlan(BaseModel):
    """有效计划组合（§8.1）：Base + Task + Run Override + digest。

    与 FrozenPlan 同构（profile_id/revision/digest/profile），decide() 可直接消费；
    layers 记录组合来源，digest 绑定组合后内容。
    """

    profile_id: str
    revision: int
    digest: str
    profile: ControlProfile
    layers: dict[str, Any] = Field(default_factory=dict)


def compile_effective_profile(
    task_profile: ControlProfile,
    run_override: dict[str, Any] | None = None,
    *,
    base_profile: ControlProfile | None = None,
) -> ControlProfile:
    """编译有效 profile：只允许收紧（§8.1/§3.3），放宽即 ProfileError。"""
    if base_profile is not None and base_profile.profile_id != task_profile.profile_id:
        pass  # base 仅贡献 required 并集，不要求同 id
    required = set(task_profile.checks.required)
    excluded = set(task_profile.checks.excluded)
    if base_profile is not None:
        required |= set(base_profile.checks.required)
        excluded |= set(base_profile.checks.excluded)
    data = task_profile.model_dump(mode="json")
    data["checks"]["required"] = sorted(required)
    data["checks"]["excluded"] = sorted(excluded)
    compiled = normalize_profile(data)
    run = run_override or {}
    unknown_keys = set(run) - {"exclude_add", "mode_tighten", "budget_cap",
                               "repair_max_rounds", "tolerance_tighten"}
    if unknown_keys:
        raise ProfileError(f"run_override 未知键: {sorted(unknown_keys)}")
    for dim in run.get("exclude_add") or []:
        if dim in compiled.checks.required:
            raise ProfileError(f"run 不得排除 required 检查: {dim}")
        if dim not in compiled.checks.excluded:
            compiled.checks.excluded.append(dim)
    for dim, mode in (run.get("mode_tighten") or {}).items():
        if mode not in _MODE_RANK:
            raise ProfileError(f"run mode 非法: {dim}={mode}")
        current = compiled.checks.modes.get(dim, "block" if dim in required else "required")
        if _MODE_RANK[mode] < _MODE_RANK[current]:
            raise ProfileError(f"run 不得放宽 {dim}（{current}→{mode}）")
        compiled.checks.modes[dim] = mode  # type: ignore[assignment]
    cap = run.get("budget_cap") or {}
    for key in ("max_audit_calls", "max_repair_calls"):
        if key in cap:
            old = getattr(compiled.budget, key)
            if int(cap[key]) > old:
                raise ProfileError(f"run 不得放宽 budget.{key}（{old}→{cap[key]}）")
            setattr(compiled.budget, key, int(cap[key]))
    if "repair_max_rounds" in run:
        if int(run["repair_max_rounds"]) > compiled.repair.max_rounds:
            raise ProfileError("run 不得放宽 repair.max_rounds")
        compiled.repair.max_rounds = int(run["repair_max_rounds"])
    for category, level in (run.get("tolerance_tighten") or {}).items():
        if level not in _TOLERANCE_RANK:
            raise ProfileError(f"run tolerance 非法: {category}={level}")
        old = (compiled.tolerance or {}).get(category, "allowed")
        if old not in _TOLERANCE_RANK:
            raise ProfileError(f"profile tolerance 非法: {category}={old}")
        if _TOLERANCE_RANK[level] < _TOLERANCE_RANK[old]:
            raise ProfileError(f"run 不得放宽 tolerance[{category}]（{old}→{level}）")
        compiled.tolerance[category] = level
    return normalize_profile(compiled.model_dump(mode="json"))


def compose_effective_plan(
    task_frozen: FrozenPlan,
    run_override: dict[str, Any] | None = None,
    *,
    base_profile: ControlProfile | None = None,
) -> ComposedPlan:
    """组合有效计划并绑定 digest（含层信息，防旧结果复用）。"""
    compiled = compile_effective_profile(
        task_frozen.profile, run_override, base_profile=base_profile)
    layers: dict[str, Any] = {
        "task_revision": task_frozen.revision,
        "task_digest": task_frozen.digest,
        "base_profile": base_profile.profile_id if base_profile else "",
        "run_override": run_override or {},
    }
    digest = "plan-" + hashlib.sha256(
        (plan_digest(compiled, task_frozen.revision)
         + json.dumps(layers, ensure_ascii=False, sort_keys=True)
         ).encode("utf-8")).hexdigest()[:32]
    return ComposedPlan(profile_id=task_frozen.profile_id,
                        revision=task_frozen.revision, digest=digest,
                        profile=compiled, layers=layers)


def normalize_profile(data: dict[str, Any]) -> ControlProfile:
    """归一化 + 冲突检查。非法直接 ProfileError（fail-closed）。"""
    try:
        profile = ControlProfile.model_validate(data)
    except Exception as exc:
        raise ProfileError(f"profile schema 非法: {exc}") from exc
    conflicts: list[str] = []
    if profile.baseline.independence_required not in (
        "self_check", "separate_context", "separate_actor", "human_required",
    ):
        conflicts.append(
            f"baseline.independence_required 非法: {profile.baseline.independence_required}")
    overlap = set(profile.checks.required) & set(profile.checks.excluded)
    if overlap:
        conflicts.append(f"required 与 excluded 重叠: {sorted(overlap)}")
    for name, mode in profile.checks.modes.items():
        if name in profile.checks.excluded and mode != "ignore":
            conflicts.append(f"excluded 检查 {name} 的 mode 必须为 ignore（现为 {mode}）")
        if name in profile.checks.required and mode == "ignore":
            conflicts.append(f"required 检查 {name} 的 mode 不能为 ignore")
    if profile.repair.max_rounds < 0:
        conflicts.append("repair.max_rounds 不能为负")
    if profile.repair.max_rounds > SYSTEM_MAX_ROUNDS:
        conflicts.append(f"repair.max_rounds 超出系统上限 {SYSTEM_MAX_ROUNDS}")
    if not profile.stop_when:
        conflicts.append("stop_when 不可为空（至少声明一个停止条件）")
    for mode in profile.checks.modes.values():
        if mode not in _MODE_RANK:
            conflicts.append(f"未知 mode: {mode}")
    for category, level in profile.tolerance.items():
        if level not in _TOLERANCE_RANK:
            conflicts.append(f"tolerance[{category}] 非法: {level}")
    if profile.budget.max_audit_calls < 0 or profile.budget.max_repair_calls < 0:
        conflicts.append("budget 调用数不能为负")
    if profile.budget.max_audit_calls > SYSTEM_MAX_AUDIT_CALLS:
        conflicts.append(f"budget.max_audit_calls 超出系统上限 {SYSTEM_MAX_AUDIT_CALLS}")
    if profile.budget.max_repair_calls > SYSTEM_MAX_REPAIR_CALLS:
        conflicts.append(f"budget.max_repair_calls 超出系统上限 {SYSTEM_MAX_REPAIR_CALLS}")
    if conflicts:
        raise ProfileError("; ".join(conflicts))
    return profile


def _canonical(profile: ControlProfile, revision: int) -> str:
    payload = profile.model_dump(mode="json")
    payload["profile_revision"] = revision
    payload["format_version"] = FORMAT_VERSION
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def plan_digest(profile: ControlProfile, revision: int) -> str:
    """确定性 digest：同 profile 同 revision 必同值（含 revision 防旧结果复用）。"""
    return "plan-" + hashlib.sha256(_canonical(profile, revision).encode("utf-8")).hexdigest()[:32]


def _revision_files(root: Path, profile_id: str) -> list[int]:
    d = _profiles_dir(root)
    if not d.is_dir():
        return []
    revs: list[int] = []
    for p in d.glob(f"{profile_id}.r*.json"):
        try:
            revs.append(int(p.stem.rsplit(".r", 1)[1]))
        except (ValueError, IndexError):
            continue
    return sorted(revs)


def save_draft(root: Path | str, profile: ControlProfile) -> Path:
    """存草稿（可覆盖）；冻结后不可变。"""
    from .scope import validate_identifier

    validate_identifier(profile.profile_id, kind="profile id")
    d = _profiles_dir(Path(root))
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{profile.profile_id}.draft.json"
    path.write_text(
        json.dumps({"format_version": FORMAT_VERSION,
                    "profile": profile.model_dump(mode="json")},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_draft(root: Path | str, profile_id: str) -> ControlProfile:
    path = _profiles_dir(Path(root)) / f"{profile_id}.draft.json"
    if not path.is_file():
        raise ProfileError(f"无草稿: {profile_id}（先 profile create）")
    import json as _json

    data = _json.loads(path.read_text(encoding="utf-8"))
    return normalize_profile(data.get("profile") or {})


def freeze_profile(root: Path | str, profile_id: str) -> FrozenPlan:
    """冻结新 revision（只增不改；同内容重复冻结产生新 revision 但同 digest 基）。"""
    from .scope import validate_identifier

    validate_identifier(profile_id, kind="profile id")
    root = Path(root)
    profile = load_draft(root, profile_id)
    revs = _revision_files(root, profile_id)
    revision = (revs[-1] if revs else 0) + 1
    digest = plan_digest(profile, revision)
    frozen = FrozenPlan(profile_id=profile_id, revision=revision,
                        digest=digest, profile=profile)
    path = _profiles_dir(root) / f"{profile_id}.r{revision}.json"
    if path.exists():
        raise ProfileError(f"revision 已冻结不可改: {path.name}")
    path.write_text(frozen.model_dump_json(ensure_ascii=False, indent=2), encoding="utf-8")
    return frozen


def load_frozen(root: Path | str, profile_id: str, revision: int) -> FrozenPlan:
    from .scope import validate_identifier

    validate_identifier(profile_id, kind="profile id")
    path = _profiles_dir(Path(root)) / f"{profile_id}.r{revision}.json"
    if not path.is_file():
        raise ProfileError(f"无此冻结 revision: {profile_id}.r{revision}")
    frozen = FrozenPlan.model_validate_json(path.read_text(encoding="utf-8"))
    # 防篡改：内容重算 digest 必须与记录一致（§15.12/§12.3 旧 digest 不可复用）。
    if plan_digest(frozen.profile, frozen.revision) != frozen.digest:
        raise ProfileError(f"冻结文件被篡改: {path.name}（内容与 digest 不一致）")
    return frozen


def list_frozen(root: Path | str) -> list[FrozenPlan]:
    """列出全部冻结 revision（坏文件跳过，只读）。"""
    d = _profiles_dir(Path(root))
    if not d.is_dir():
        return []
    out: list[FrozenPlan] = []
    for path in sorted(d.glob("*.r*.json")):
        try:
            out.append(FrozenPlan.model_validate_json(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out

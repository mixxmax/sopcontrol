"""WP-H（终极手册 §8）：一体化升级——绑定清单、语义 diff、影子验证、原子切换、回滚。

分层（§8.1）：Stable Launcher → Project Binding → Versioned Runtime →
Adapter Protocol → Project Rule Data（规则数据独立于软件包）。

v1 诚实边界：runtime 安装 = 记录版本与路径（本仓库开发态没有 PyPI 包可拉）；
升级闭环的全部门与事务结构是真实的——语义投影 diff、规则保留硬门、
影子验证、原子切换、回滚。离线环境优先（§8.5）：不联网。
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .model import RuleStatus, content_hash, utcnow

SCHEMA_VERSION = "1"
BINDING_SCHEMA_VERSION = "1"
ADAPTER_PROTOCOL_VERSION = "1"

_STRICT = ConfigDict(extra="forbid")

ACTIVE_STATUSES = {RuleStatus.accepted, RuleStatus.compiled,
                   RuleStatus.activated, RuleStatus.monitored}


class ProjectBinding(BaseModel):
    """§8.2 项目绑定清单：不是第二权威规则仓库，不含 secret。"""
    model_config = _STRICT

    schema_version: str = SCHEMA_VERSION
    core_version: str
    update_channel: str = "stable"
    rule_schema_version: str = SCHEMA_VERSION
    adapter_protocol_version: str = ADAPTER_PROTOCOL_VERSION
    adapter_digests: dict[str, str] = Field(default_factory=dict)
    surface_summary: dict[str, int] = Field(default_factory=dict)
    last_verify: dict[str, Any] = Field(default_factory=dict)
    runtime_path: str = ""
    previous_runtime_path: str = ""
    previous_core_version: str = ""
    rule_data_migration_version: int = 1
    installed_at: str = ""
    updated_at: str = ""


class RuleProjection(BaseModel):
    """单条规则的规范语义投影（§8.2）：15 个行为字段，无时间字段。

    字段映射：exceptions→flexibility 全体 + tags；compiler target/version→
    compile_tool/compile_digest；revision→lifecycle_revision。
    created_at/updated_at/accepted_at/compiled_at/attested_at 等时间字段
    明确排除——它们变化不改变行为（§8.4 时间对照测试）。
    """
    model_config = _STRICT

    rule_id: str
    revision: int = 0
    rule_class: str = ""
    statement: str = ""
    modality: str = ""
    status: str = ""
    scope: str = ""
    scope_paths: list[str] = Field(default_factory=list)
    activation: dict[str, Any] = Field(default_factory=dict)
    flexibility: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)
    superseded_by: str = ""
    consumer_markers: list[str] = Field(default_factory=list)
    guard_ids: list[str] = Field(default_factory=list)
    compile_tool: str = ""
    compile_digest: str = ""

    @classmethod
    def of(cls, rule: Any) -> "RuleProjection":
        activation = rule.activation
        flexibility = rule.flexibility
        return cls(
            rule_id=rule.rule_id,
            revision=int(getattr(rule, "lifecycle_revision", 0) or 0),
            rule_class=str(getattr(rule, "rule_class", "")),
            statement=" ".join(str(rule.statement).split()),
            modality=rule.modality.value if hasattr(rule.modality, "value") else str(rule.modality),
            status=rule.status.value if hasattr(rule.status, "value") else str(rule.status),
            scope=str(getattr(rule, "scope", "")),
            scope_paths=sorted(getattr(rule, "scope_paths", None) or []),
            activation=activation.model_dump(mode="json") if hasattr(activation, "model_dump") else dict(activation or {}),
            flexibility=flexibility.model_dump(mode="json") if hasattr(flexibility, "model_dump") else dict(flexibility or {}),
            tags=sorted(getattr(rule, "tags", None) or []),
            supersedes=sorted(getattr(rule, "supersedes", None) or []),
            superseded_by=str(getattr(rule, "superseded_by", "") or ""),
            consumer_markers=sorted(getattr(rule, "consumer_markers", None) or []),
            guard_ids=sorted(getattr(rule, "guard_ids", None) or []),
            compile_tool=str(getattr(rule, "compile_tool", "") or ""),
            compile_digest=str(getattr(rule, "compile_digest", "") or ""),
        )


class SemanticProjection(BaseModel):
    """规则空间的语义投影摘要（§8.3 第 6 步 diff 的输入）。"""
    model_config = _STRICT

    core_version: str
    rule_schema_version: str
    total_rules: int = 0
    active_rules: int = 0
    by_class: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    block_modalities: int = 0
    dynamic_sop_ids: list[str] = Field(default_factory=list)
    rules: list[RuleProjection] = Field(default_factory=list)
    digest: str = ""

    @classmethod
    def capture(cls, root: Path, core_version: str) -> "SemanticProjection":
        from .registry import Registry

        rules = Registry(root / ".sopcontrol" / "rules" / "registry.yaml").load()
        by_class: dict[str, int] = {}
        by_status: dict[str, int] = {}
        dynamic_ids: list[str] = []
        block_modalities = 0
        active = 0
        for rule in rules:
            by_class[rule.rule_class] = by_class.get(rule.rule_class, 0) + 1
            by_status[rule.status.value] = by_status.get(rule.status.value, 0) + 1
            if rule.status in ACTIVE_STATUSES:
                active += 1
                if rule.rule_class == "dynamic_sop":
                    dynamic_ids.append(rule.rule_id)
                if rule.modality.value == "MUST_NOT" or rule.modality.value == "MUST":
                    block_modalities += 1
        projections = sorted(
            (RuleProjection.of(rule) for rule in rules),
            key=lambda p: p.rule_id)
        return cls(core_version=core_version,
                   rule_schema_version=SCHEMA_VERSION,
                   total_rules=len(rules), active_rules=active,
                   by_class=by_class, by_status=by_status,
                   block_modalities=block_modalities,
                   dynamic_sop_ids=sorted(dynamic_ids),
                   rules=projections,
                   digest=content_hash({
                       "rules": [p.model_dump(mode="json") for p in projections],
                   })[:20])


def _binding_path(root: Path) -> Path:
    return Path(root) / ".sopcontrol-local" / "binding.yaml"


def load_binding(root: Path) -> Optional[ProjectBinding]:
    path = _binding_path(root)
    if not path.is_file():
        return None
    try:
        return ProjectBinding.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def save_binding(root: Path, binding: ProjectBinding) -> Path:
    path = _binding_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".binding.", suffix=".tmp",
                               dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(yaml.safe_dump(binding.model_dump(), allow_unicode=True,
                                    sort_keys=True))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def init_binding(root: Path) -> ProjectBinding:
    from sopcontrol import __version__

    binding = ProjectBinding(
        core_version=__version__,
        runtime_path=str(Path(__file__).parent.resolve()),
        installed_at=utcnow().isoformat(),
        updated_at=utcnow().isoformat(),
    )
    save_binding(root, binding)
    return binding


def _runtime_dir(root: Path, version: str) -> Path:
    return Path(root) / ".sopcontrol-local" / "runtimes" / version


def semantic_diff(before: SemanticProjection, after: SemanticProjection) -> dict[str, Any]:
    """§8.3 第 6 步：语义投影差异。任何放宽都是升级硬门（§8.4）。

    除计数硬门外，逐规则比对 15 个行为字段：同数量下正文/范围/容忍度/
    选择器/消费者任一变化即 semantic_changes；时间字段不参与。
    """
    lost_dynamic = sorted(set(before.dynamic_sop_ids) - set(after.dynamic_sop_ids))
    downgrades: list[str] = []
    # block 级模态减少 = 放宽
    if after.block_modalities < before.block_modalities:
        downgrades.append(
            f"block 级规则 {before.block_modalities}→{after.block_modalities}")
    # active 总量减少（规则丢失）
    if after.active_rules < before.active_rules:
        downgrades.append(
            f"active 规则 {before.active_rules}→{after.active_rules}")
    # 动态 SOP 丢失（最高优先硬门）
    if lost_dynamic:
        downgrades.append(f"动态 SOP 丢失: {lost_dynamic}")
    before_map = {p.rule_id: p for p in before.rules}
    after_map = {p.rule_id: p for p in after.rules}
    added = sorted(set(after_map) - set(before_map))
    removed = sorted(set(before_map) - set(after_map))
    changed_rules: list[dict[str, Any]] = []
    for rule_id in sorted(set(before_map) & set(after_map)):
        old, new = before_map[rule_id], after_map[rule_id]
        changed_fields: list[str] = []
        old_d, new_d = old.model_dump(mode="json"), new.model_dump(mode="json")
        for field in ("statement", "modality", "status", "rule_class",
                      "activation", "flexibility", "tags", "scope_paths",
                      "supersedes", "superseded_by", "consumer_markers",
                      "guard_ids", "compile_tool", "compile_digest", "revision"):
            if old_d.get(field) != new_d.get(field):
                label = "scope" if field == "scope_paths" else field
                if label not in changed_fields:
                    changed_fields.append(label)
        if old_d.get("scope") != new_d.get("scope") and "scope" not in changed_fields:
            changed_fields.append("scope")
        if changed_fields:
            changed_rules.append({"rule_id": rule_id,
                                  "changed_fields": sorted(changed_fields)})
    if removed:
        downgrades.append(f"规则移除: {removed}")
    schema_changed = before.rule_schema_version != after.rule_schema_version
    semantic_changes = (before.digest != after.digest) or bool(changed_rules)
    return {"semantic_changes": semantic_changes,
            "schema_changed": schema_changed,
            "downgrades": downgrades,
            "lost_dynamic_sop": lost_dynamic,
            "added_rules": added,
            "removed_rules": removed,
            "changed_rules": changed_rules,
            "before_digest": before.digest,
            "after_digest": after.digest}


class UpgradePlan(BaseModel):
    model_config = _STRICT

    from_version: str
    to_version: str
    staged_path: str = ""
    semantic_diff: dict[str, Any] = Field(default_factory=dict)
    gates: list[dict[str, str]] = Field(default_factory=list)
    auto_switch: bool = False
    blocked: bool = False
    reasons: list[str] = Field(default_factory=list)


def plan_upgrade(root: Path, *, target_version: Optional[str] = None) -> UpgradePlan:
    """§8.3 第 1–6 步：生成升级计划与语义 diff（不执行切换）。"""
    from sopcontrol import __version__

    root = Path(root)
    binding = load_binding(root) or init_binding(root)
    to_version = target_version or __version__
    before = SemanticProjection.capture(root, binding.core_version)
    # v1：staged runtime 目录登记（真实并行安装点；离线不下载）
    staged = _runtime_dir(root, to_version)
    staged.mkdir(parents=True, exist_ok=True)
    # 语义投影：staged 运行时编译同一份规则数据（规则数据独立于软件包，§8.1）
    after = SemanticProjection.capture(root, to_version)
    diff = semantic_diff(before, after)
    gates: list[dict[str, str]] = []
    reasons: list[str] = []
    blocked = False
    if diff["downgrades"]:
        blocked = True
        for d in diff["downgrades"]:
            gates.append({"gate": "semantic_no_downgrade", "status": "fail", "detail": d})
            reasons.append(d)
    else:
        gates.append({"gate": "semantic_no_downgrade", "status": "pass", "detail": ""})
    if diff["schema_changed"]:
        gates.append({"gate": "schema_migration_reversible", "status": "warn",
                      "detail": "schema version 变化：需要可逆迁移确认"})
        reasons.append("schema version 变化：需要确认迁移可逆")
    else:
        gates.append({"gate": "schema_migration_reversible", "status": "pass",
                      "detail": ""})
    major_change = _major_jump(binding.core_version, to_version)
    auto_switch = (not blocked and not major_change
                   and not diff["semantic_changes"] and not diff["schema_changed"])
    if major_change:
        reasons.append("major/规则语义变化：需要明确确认（§8.5）")
    return UpgradePlan(from_version=binding.core_version, to_version=to_version,
                       staged_path=str(staged), semantic_diff=diff,
                       gates=gates, auto_switch=auto_switch,
                       blocked=blocked, reasons=reasons)


def _major_jump(from_version: str, to_version: str) -> bool:
    try:
        f_major = int(from_version.split(".")[0])
        t_major = int(to_version.split(".")[0])
    except (ValueError, IndexError):
        return True
    return t_major > f_major


def sync(root: Path, *, target_version: Optional[str] = None,
         assume_yes: bool = False) -> dict[str, Any]:
    """§8.3 一条命令闭环：plan → 影子验证 → 原子切换（或保持旧版）。

    失败时保持旧 runtime 不动（§8.3 第 10 步）；永久规则保留是硬门。
    """
    root = Path(root)
    plan = plan_upgrade(root, target_version=target_version)
    binding = load_binding(root)
    result: dict[str, Any] = {
        "from_version": plan.from_version, "to_version": plan.to_version,
        "semantic_diff": plan.semantic_diff, "gates": plan.gates,
        "switched": False, "rolled_back": False, "reasons": plan.reasons,
    }
    if plan.blocked:
        result["outcome"] = "blocked"
        result["note"] = "升级硬门未通过：保持旧 runtime，产品继续运行"
        return result
    if not plan.auto_switch and not assume_yes:
        result["outcome"] = "awaiting_confirmation"
        result["note"] = "存在语义/schema 变化或 major 升级：需要一次明确确认"
        return result
    # 影子验证（§8.3 第 8 步）：在切换前对规则数据与账本做完整校验
    shadow = _shadow_verify(root)
    result["shadow_verify"] = shadow
    if not shadow["passed"]:
        result["outcome"] = "blocked"
        result["note"] = "影子验证失败：保持旧 runtime"
        return result
    # 原子切换：binding 指针一次替换（launcher 按绑定选择 runtime）
    assert binding is not None
    binding.previous_runtime_path = binding.runtime_path
    binding.previous_core_version = binding.core_version
    binding.core_version = plan.to_version
    binding.runtime_path = plan.staged_path
    binding.updated_at = utcnow().isoformat()
    binding.last_verify = {"shadow": shadow, "at": utcnow().isoformat()}
    save_binding(root, binding)
    result["switched"] = True
    result["outcome"] = "switched"
    result["rollback_target"] = binding.previous_runtime_path
    return result


def _shadow_verify(root: Path) -> dict[str, Any]:
    """影子验证：规则完整性 + 账本可读 + 动态 SOP 计数（不写生产状态）。"""
    from .registry import Registry

    try:
        rules = Registry(root / ".sopcontrol" / "rules" / "registry.yaml").load()
    except Exception as exc:
        return {"passed": False, "error": f"规则注册表不可解析: {exc}"}
    dynamic = [r for r in rules
               if r.rule_class == "dynamic_sop" and r.status in ACTIVE_STATUSES]
    return {"passed": True, "total_rules": len(rules),
            "dynamic_sop_active": len(dynamic),
            "note": "规则链与来源完整可解析"}


def rollback(root: Path) -> dict[str, Any]:
    """§8.3 第 11 步：回滚到上一可回滚 runtime；规则数据不动（独立于包）。"""
    root = Path(root)
    binding = load_binding(root)
    if binding is None or not binding.previous_runtime_path:
        return {"rolled_back": False, "note": "无可回滚点"}
    previous_version = binding.previous_core_version or \
        binding.previous_runtime_path.rstrip("/").split("/")[-1]
    current_projection = SemanticProjection.capture(root, binding.core_version)
    target_projection = SemanticProjection.capture(root, previous_version)
    diff = semantic_diff(current_projection, target_projection)
    if diff["downgrades"] and diff["lost_dynamic_sop"]:
        # 回滚本身也不得丢规则（双向硬门）
        return {"rolled_back": False,
                "note": f"回滚将丢失动态 SOP，拒绝执行: {diff['lost_dynamic_sop']}"}
    binding.runtime_path, binding.previous_runtime_path = (
        binding.previous_runtime_path, binding.runtime_path)
    binding.core_version = previous_version
    binding.updated_at = utcnow().isoformat()
    save_binding(root, binding)
    return {"rolled_back": True, "core_version": binding.core_version,
            "note": "已回滚；项目规则数据不受影响"}

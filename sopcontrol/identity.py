"""项目身份（Phase 6 最小切片）：跨 harness 识别同一项目的稳定 id。

不做全局 daemon。身份落在 `.sopcontrol/identity.yaml`，内容由项目根路径
规范化后哈希——同根同 id，换机器路径变则 id 变（诚实边界，记 R11）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

from .model import content_hash, utcnow


class ProjectIdentity(BaseModel):
    project_id: str
    root: str
    created_at: str = ""
    note: str = "跨 harness 识别用；权威规则仍在 registry（Phase 6 种子）"


def identity_path(root: Path) -> Path:
    return Path(root) / ".sopcontrol" / "identity.yaml"


def compute_project_id(root: Path) -> str:
    canonical = str(Path(root).resolve())
    return "proj-" + content_hash({"root": canonical})


def load_identity(root: Path) -> Optional[ProjectIdentity]:
    path = identity_path(root)
    if not path.exists():
        return None
    return ProjectIdentity.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def ensure_identity(root: Path) -> ProjectIdentity:
    """已有则校验 root 字段；缺失则创建。路径变更导致 id 漂移时更新并注明。"""
    root = Path(root).resolve()
    existing = load_identity(root)
    expected_id = compute_project_id(root)
    if existing and existing.project_id == expected_id and existing.root == str(root):
        return existing
    identity = ProjectIdentity(
        project_id=expected_id,
        root=str(root),
        created_at=utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        note=(
            "路径变化后重新派生 id"
            if existing and existing.project_id != expected_id
            else "跨 harness 识别用；权威规则仍在 registry（Phase 6 种子）"
        ),
    )
    path = identity_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(identity.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return identity

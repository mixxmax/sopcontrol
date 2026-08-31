"""模型行为安全上限：与可压缩遥测分离的小型持久化状态。"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field

from .model import content_hash, utcnow

BEHAVIOR_STATE_REL = ".sopcontrol/evidence/behavior-ceilings.yaml"
CEILING_TTL = timedelta(days=30)
MAX_SOURCE_EVENTS = 20


class BehaviorCeiling(BaseModel):
    model: str
    ceiling: Literal["weak"] = "weak"
    activated_at: datetime
    expires_at: datetime
    source_event_ids: list[str] = Field(default_factory=list)


class BehaviorState(BaseModel):
    version: int = 1
    ceilings: dict[str, BehaviorCeiling] = Field(default_factory=dict)
    checksum: str = ""

    def expected_checksum(self) -> str:
        return content_hash(
            self.model_dump(exclude={"checksum"}, mode="json")
        )


class BehaviorStateLoad(BaseModel):
    state: BehaviorState = Field(default_factory=BehaviorState)
    integrity_ok: bool = True


def behavior_state_path(root: Path) -> Path:
    return Path(root) / BEHAVIOR_STATE_REL


def load_behavior_state(root: Path) -> BehaviorStateLoad:
    path = behavior_state_path(root)
    if not path.exists():
        return BehaviorStateLoad()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        state = BehaviorState.model_validate(data)
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        return BehaviorStateLoad(integrity_ok=False)
    return BehaviorStateLoad(
        state=state,
        integrity_ok=bool(state.checksum) and state.checksum == state.expected_checksum(),
    )


def _save_behavior_state(root: Path, state: BehaviorState) -> bool:
    path = behavior_state_path(root)
    try:
        state.checksum = state.expected_checksum()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(state.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def activate_behavior_ceiling(
    root: Path,
    *,
    model: str,
    source_event_id: str,
    now: Optional[datetime] = None,
) -> bool:
    """记录一次不可由普通遥测驱逐的 weak 上限；重复失败续期。"""
    if not model:
        return False
    loaded = load_behavior_state(root)
    if not loaded.integrity_ok:
        return False
    current = now or utcnow()
    previous = loaded.state.ceilings.get(model)
    sources = list(previous.source_event_ids) if previous else []
    if source_event_id and source_event_id not in sources:
        sources.append(source_event_id)
    loaded.state.ceilings[model] = BehaviorCeiling(
        model=model,
        activated_at=previous.activated_at if previous else current,
        expires_at=current + CEILING_TTL,
        source_event_ids=sources[-MAX_SOURCE_EVENTS:],
    )
    return _save_behavior_state(root, loaded.state)


def effective_behavior_ceiling(
    root: Path,
    *,
    model: str,
    now: Optional[datetime] = None,
) -> tuple[Optional[Literal["weak"]], bool, list[str]]:
    """返回当前上限、完整性与来源。状态损坏时对任何身份 fail-closed 为 weak。"""
    loaded = load_behavior_state(root)
    if not loaded.integrity_ok:
        return "weak", False, []
    record = loaded.state.ceilings.get(model)
    if record is None:
        return None, True, []
    if (now or utcnow()) > record.expires_at:
        return None, True, record.source_event_ids
    return record.ceiling, True, record.source_event_ids

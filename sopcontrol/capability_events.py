"""被动能力事件：复用既有控制结果，内容寻址、去重、可重放。

事件只记录客观结果，不参与模型画像或权限计算。采集失败不得阻断原动作。
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .model import content_hash, utcnow

CAPABILITY_EVENT_REL = ".sopcontrol/evidence/capability-events.jsonl"
MAX_CAPABILITY_EVENTS = 500


class CapabilityEvent(BaseModel):
    event_id: str = ""
    kind: str
    subject: str
    outcome: str
    model: str = ""
    tier: str = "unknown"
    detail: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=utcnow)

    def model_post_init(self, _) -> None:
        if not self.event_id:
            payload = self.model_dump(exclude={"event_id", "observed_at"}, mode="json")
            self.event_id = "ce-" + content_hash(payload)


def capability_event_path(root: Path) -> Path:
    return Path(root) / CAPABILITY_EVENT_REL


def load_capability_events(root: Path) -> list[CapabilityEvent]:
    path = capability_event_path(root)
    try:
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    except OSError:
        return []

    events: list[CapabilityEvent] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            events.append(CapabilityEvent.model_validate(data))
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return events


def append_capability_event(root: Path, event: CapabilityEvent) -> bool:
    """追加一条新事件；重复或写入失败返回 False，且不影响原动作。"""
    path = capability_event_path(root)
    try:
        existing = load_capability_events(root)
        if any(item.event_id == event.event_id for item in existing):
            return False
        kept = (existing + [event])[-MAX_CAPABILITY_EVENTS:]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for item in kept:
                handle.write(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def replay_capability_events(events: list[CapabilityEvent]) -> dict[str, Any]:
    """确定性重放摘要；排序与时间不影响结果。"""
    unique = {event.event_id: event for event in events}

    def counts(field: str) -> dict[str, int]:
        values = [str(getattr(event, field) or "") for event in unique.values()]
        return dict(sorted(Counter(value for value in values if value).items()))

    return {
        "event_count": len(unique),
        "by_kind": counts("kind"),
        "by_outcome": counts("outcome"),
        "by_model": counts("model"),
        "by_tier": counts("tier"),
    }

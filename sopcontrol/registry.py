"""规则注册表：.sopcontrol/rules/registry.yaml 的载入、校验与生命周期迁移。"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import tempfile
import threading

import yaml

from .model import (
    ALLOWED_TRANSITIONS,
    ACTIVE_RULE_STATUSES,
    RETIRED_RULE_STATUSES,
    Rule,
    RuleStatus,
    content_hash,
    utcnow,
)


class RegistryError(Exception):
    pass


class _RegistryPathLock:
    def __init__(self) -> None:
        self.thread_lock = threading.RLock()
        self.local = threading.local()


_PATH_LOCKS: dict[str, _RegistryPathLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


class Registry:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _lock_path(self) -> Path:
        resolved = self.path.resolve()
        if self.path.parent.name == "rules" and self.path.parent.parent.name == ".sopcontrol":
            root = self.path.parent.parent.parent
        else:
            root = self.path.parent
        return root / ".sopcontrol-local" / "locks" / f"registry-{content_hash(str(resolved))}.lock"

    @contextmanager
    def exclusive(self):
        """同一路径的进程内与跨进程可重入写锁。"""
        key = str(self.path.resolve())
        with _PATH_LOCKS_GUARD:
            state = _PATH_LOCKS.setdefault(key, _RegistryPathLock())
        with state.thread_lock:
            depth = getattr(state.local, "depth", 0)
            if depth == 0:
                lock_path = self._lock_path()
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                descriptor = lock_path.open("a+")
                fcntl.flock(descriptor.fileno(), fcntl.LOCK_EX)
                state.local.descriptor = descriptor
            state.local.depth = depth + 1
            try:
                yield
            finally:
                state.local.depth -= 1
                if state.local.depth == 0:
                    descriptor = state.local.descriptor
                    fcntl.flock(descriptor.fileno(), fcntl.LOCK_UN)
                    descriptor.close()
                    del state.local.descriptor

    def load(self) -> list[Rule]:
        if not self.path.exists():
            raise RegistryError(
                f"未找到规则注册表 {self.path}；先在该项目运行 sopctl init"
            )
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        rules: list[Rule] = []
        seen: set[str] = set()
        for raw in data.get("rules", []):
            rule = Rule.model_validate(raw)
            if rule.rule_id in seen:
                raise RegistryError(f"注册表中存在重复 rule_id: {rule.rule_id}")
            seen.add(rule.rule_id)
            rules.append(rule)
        return rules

    def _write(self, rules: list[Rule]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"rules": [r.model_dump(mode="json") for r in rules]}
        serialized = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _save_locked(self, rules: list[Rule]) -> None:
        seen: set[str] = set()
        for rule in rules:
            if rule.rule_id in seen:
                raise RegistryError(f"注册表中存在重复 rule_id: {rule.rule_id}")
            seen.add(rule.rule_id)
        previous = {rule.rule_id: rule for rule in self.load()} if self.path.exists() else {}
        incoming = {rule.rule_id: rule for rule in rules}
        for rule in rules:
            old = previous.get(rule.rule_id)
            if rule.status in RETIRED_RULE_STATUSES and (
                old is None or old.status not in RETIRED_RULE_STATUSES
            ):
                raise RegistryError(
                    "永久退出状态不能通过普通 save 写入；请使用 deprecate/supersede 预览确认流程"
                )
        for rule_id, old in previous.items():
            if old.status not in RETIRED_RULE_STATUSES:
                continue
            current = incoming.get(rule_id)
            if current is None or current.model_dump(mode="json") != old.model_dump(mode="json"):
                raise RegistryError(
                    f"历史退出记录 {rule_id} 是终态，普通 save 不得删除、恢复或改写"
                )
        self._write(rules)

    def save(self, rules: list[Rule]) -> None:
        """保存普通规则更新；退休记录只能由 confirm_retirement 创建且保持终态。"""
        with self.exclusive():
            self._save_locked(rules)

    def add(self, rule: Rule) -> None:
        with self.exclusive():
            if rule.status in RETIRED_RULE_STATUSES:
                raise RegistryError(
                    "永久退出状态不能通过普通规则登记创建；请先登记非退休规则，再使用 deprecate/supersede 预览确认流程"
                )
            rules = self.load()
            if any(r.rule_id == rule.rule_id for r in rules):
                raise RegistryError(
                    f"rule_id {rule.rule_id} 已存在；如要替换旧规则请使用 supersede 流程，而不是覆盖"
                )
            rules.append(rule)
            self._save_locked(rules)

    def get(self, rule_id: str) -> Rule:
        for rule in self.load():
            if rule.rule_id == rule_id:
                return rule
        known = ", ".join(r.rule_id for r in self.load()) or "（注册表为空）"
        raise RegistryError(f"未找到规则 {rule_id}；现有规则: {known}")

    def _retirement_preview(
        self,
        rules: list[Rule],
        rule_id: str,
        *,
        action: str,
        reason: str,
        actor: str,
        replacement: str = "",
    ) -> dict:
        if action not in {"deprecate", "supersede"}:
            raise RegistryError(f"未知规则退出动作 {action!r}")
        if not reason.strip():
            raise RegistryError("规则退出必须提供非空 reason")
        if not actor.strip() or actor.strip().lower() == "agent":
            raise RegistryError("规则退出必须记录人工确认人，agent 自签无效")
        by_id = {rule.rule_id: rule for rule in rules}
        rule = by_id.get(rule_id)
        if rule is None:
            raise RegistryError(f"未找到规则 {rule_id}")
        if rule.status not in ACTIVE_RULE_STATUSES:
            raise RegistryError(
                f"规则 {rule_id} 当前为 {rule.status.value}，不是当前有效规则，不能执行永久退出"
            )
        replacement_rule = None
        if action == "supersede":
            if not replacement or replacement == rule_id:
                raise RegistryError("supersede 必须指定另一条 replacement 规则")
            replacement_rule = by_id.get(replacement)
            if replacement_rule is None:
                raise RegistryError(f"替代规则 {replacement} 不存在")
            replacement_states = ACTIVE_RULE_STATUSES | {
                RuleStatus.proposed,
                RuleStatus.clarified,
            }
            if replacement_rule.status not in replacement_states:
                raise RegistryError(
                    f"替代规则 {replacement} 当前为 {replacement_rule.status.value}，"
                    "必须是 proposed/clarified 或当前有效规则"
                )
            if replacement_rule.scope != rule.scope:
                raise RegistryError(
                    f"替代规则作用域不一致：{rule_id}={rule.scope}，{replacement}={replacement_rule.scope}"
                )
        elif replacement:
            raise RegistryError("deprecate 不接受 replacement；需要替代关系请使用 supersede")

        payload = {
            "registry": [item.model_dump(mode="json") for item in rules],
            "rule_id": rule_id,
            "action": action,
            "replacement": replacement,
            "reason": reason.strip(),
            "actor": actor.strip(),
        }
        return {
            "preview_id": content_hash(payload),
            "rule_id": rule_id,
            "action": action,
            "replacement": replacement,
            "reason": reason.strip(),
            "actor": actor.strip(),
            "consumer_markers": list(rule.consumer_markers),
            "guard_ids": list(rule.guard_ids),
            "replacement_rule": replacement_rule,
        }

    def retirement_preview(
        self,
        rule_id: str,
        *,
        action: str,
        reason: str,
        actor: str,
        replacement: str = "",
    ) -> dict:
        """构造绑定完整 registry 快照的退出预览，不修改磁盘。"""
        return self._retirement_preview(
            self.load(),
            rule_id,
            action=action,
            reason=reason,
            actor=actor,
            replacement=replacement,
        )

    def confirm_retirement(
        self,
        rule_id: str,
        *,
        action: str,
        reason: str,
        actor: str,
        preview_id: str,
        replacement: str = "",
    ) -> Rule:
        """确认内容寻址预览；一次保存更新旧规则和 replacement 两端。"""
        with self.exclusive():
            rules = self.load()
            by_id = {rule.rule_id: rule for rule in rules}
            existing = by_id.get(rule_id)
            expected_status = (
                RuleStatus.deprecated
                if action == "deprecate"
                else RuleStatus.superseded
            )
            if (
                existing is not None
                and existing.status == expected_status
                and existing.retirement_id == preview_id
                and existing.retirement_reason == reason.strip()
                and existing.retired_by == actor.strip()
                and existing.superseded_by == replacement
            ):
                return existing

            preview = self._retirement_preview(
                rules,
                rule_id,
                action=action,
                reason=reason,
                actor=actor,
                replacement=replacement,
            )
            if not preview_id or preview_id != preview["preview_id"]:
                raise RegistryError(
                    "preview_id 已失效或不匹配；registry/参数已变化，请重新运行不带 --confirm-preview 的预览"
                )

            rule = by_id[rule_id]
            if action == "supersede":
                from .conflict import find_conflicts

                successor = by_id[replacement]
                prospective = successor.model_copy(deep=True)
                prospective.status = RuleStatus.accepted
                if rule_id not in prospective.supersedes:
                    prospective.supersedes.append(rule_id)
                conflicts = find_conflicts(prospective, rules)
                if conflicts:
                    detail = "；".join(
                        conflict["reason"] for conflict in conflicts
                    )
                    raise RegistryError(
                        f"替代规则仍与其他当前有效规则冲突：{detail}；退出操作未写入"
                    )

            rule.status = expected_status
            rule.retirement_reason = preview["reason"]
            rule.retired_by = preview["actor"]
            rule.retired_at = utcnow()
            rule.retirement_id = preview_id
            if action == "supersede":
                rule.superseded_by = replacement
                successor = by_id[replacement]
                if successor.status in {RuleStatus.proposed, RuleStatus.clarified}:
                    successor.status = RuleStatus.accepted
                    if successor.accepted_at is None:
                        successor.accepted_at = utcnow()
                if rule_id not in successor.supersedes:
                    successor.supersedes.append(rule_id)
            self._write(rules)
            return rule

    def transition(self, rule_id: str, new_status: RuleStatus) -> Rule:
        from .conflict import find_conflicts

        if new_status in RETIRED_RULE_STATUSES:
            raise RegistryError(
                "永久退出状态只能通过 deprecate/supersede 预览确认流程写入"
            )
        with self.exclusive():
            rules = self.load()
            for rule in rules:
                if rule.rule_id == rule_id:
                    allowed = ALLOWED_TRANSITIONS[rule.status]
                    if new_status not in allowed:
                        options = (
                            ", ".join(
                                status.value
                                for status in sorted(allowed, key=lambda status: status.value)
                            )
                            or "（终态）"
                        )
                        raise RegistryError(
                            f"非法生命周期迁移 {rule.status.value} → {new_status.value}；"
                            f"从 {rule.status.value} 出发允许: {options}"
                        )
                    if new_status == RuleStatus.accepted:
                        conflicts = find_conflicts(rule, rules)
                        if conflicts:
                            detail = "；".join(c["reason"] for c in conflicts)
                            raise RegistryError(
                                f"规则冲突（14.1 场景10）：{detail}。"
                                f"请先 supersede/废弃旧规则，或调整 consumer_markers，不得让相反模态并存"
                            )
                    rule.status = new_status
                    if new_status == RuleStatus.accepted and rule.accepted_at is None:
                        rule.accepted_at = utcnow()
                    self._save_locked(rules)
                    return rule
            raise RegistryError(f"未找到规则 {rule_id}")

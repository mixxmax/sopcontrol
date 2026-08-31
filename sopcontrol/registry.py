"""规则注册表：.sopcontrol/rules/registry.yaml 的载入、校验与生命周期迁移。"""
from __future__ import annotations

from pathlib import Path

import yaml

from .model import (
    ALLOWED_TRANSITIONS,
    ACTIVE_RULE_STATUSES,
    Rule,
    RuleStatus,
    content_hash,
    utcnow,
)


class RegistryError(Exception):
    pass


class Registry:
    def __init__(self, path: Path):
        self.path = Path(path)

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

    def save(self, rules: list[Rule]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"rules": [r.model_dump(mode="json") for r in rules]}
        self.path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    def add(self, rule: Rule) -> None:
        if rule.status in {RuleStatus.deprecated, RuleStatus.superseded}:
            raise RegistryError(
                "永久退出状态不能通过普通规则登记创建；请先登记非退休规则，再使用 deprecate/supersede 预览确认流程"
            )
        rules = self.load()
        if any(r.rule_id == rule.rule_id for r in rules):
            raise RegistryError(
                f"rule_id {rule.rule_id} 已存在；如要替换旧规则请使用 supersede 流程，而不是覆盖"
            )
        rules.append(rule)
        self.save(rules)

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
        rules = self.load()
        by_id = {rule.rule_id: rule for rule in rules}
        existing = by_id.get(rule_id)
        expected_status = RuleStatus.deprecated if action == "deprecate" else RuleStatus.superseded
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
                detail = "；".join(conflict["reason"] for conflict in conflicts)
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
        self.save(rules)
        return rule

    def transition(self, rule_id: str, new_status: RuleStatus) -> Rule:
        from .conflict import find_conflicts

        if new_status in {RuleStatus.deprecated, RuleStatus.superseded}:
            raise RegistryError(
                "永久退出状态只能通过 deprecate/supersede 预览确认流程写入"
            )
        rules = self.load()
        for rule in rules:
            if rule.rule_id == rule_id:
                allowed = ALLOWED_TRANSITIONS[rule.status]
                if new_status not in allowed:
                    options = ", ".join(s.value for s in sorted(allowed, key=lambda s: s.value)) or "（终态）"
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
                self.save(rules)
                return rule
        raise RegistryError(f"未找到规则 {rule_id}")

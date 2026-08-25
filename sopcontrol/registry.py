"""规则注册表：.sopcontrol/rules/registry.yaml 的载入、校验与生命周期迁移。"""
from __future__ import annotations

from pathlib import Path

import yaml

from .model import ALLOWED_TRANSITIONS, Rule, RuleStatus, utcnow


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

    def transition(self, rule_id: str, new_status: RuleStatus) -> Rule:
        from .conflict import find_conflicts

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

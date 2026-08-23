"""宪法测试：注册表强制出处、合法迁移与唯一 id——拒绝时必须给出可行动的解释。"""
import pytest
from pydantic import ValidationError

from sopcontrol.model import Modality, Rule, RuleStatus, SourceRef
from sopcontrol.registry import Registry, RegistryError


def make_rule(**overrides) -> Rule:
    base = dict(
        rule_id="REG-001",
        statement="注册表测试规则",
        modality=Modality.MUST,
        status=RuleStatus.proposed,
        source=SourceRef(type="manual_seed", ref="tests"),
    )
    base.update(overrides)
    return Rule(**base)


def test_rule_without_provenance_is_rejected():
    with pytest.raises(ValidationError):
        Rule(rule_id="X-1", statement="无出处", modality=Modality.MUST, status=RuleStatus.proposed)


def test_duplicate_rule_id_rejected(tmp_path):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([make_rule()])
    with pytest.raises(RegistryError, match="已存在"):
        registry.add(make_rule())


def test_illegal_transition_rejected_with_explanation(tmp_path):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([make_rule(status=RuleStatus.observed)])
    with pytest.raises(RegistryError) as exc_info:
        registry.transition("REG-001", RuleStatus.accepted)
    message = str(exc_info.value)
    assert "observed" in message and "proposed" in message  # 错误必须指出合法出路


def test_accept_sets_timestamp(tmp_path):
    registry = Registry(tmp_path / "registry.yaml")
    registry.save([make_rule(status=RuleStatus.proposed)])
    rule = registry.transition("REG-001", RuleStatus.accepted)
    assert rule.status == RuleStatus.accepted
    assert rule.accepted_at is not None


def test_missing_registry_message_is_actionable(tmp_path):
    registry = Registry(tmp_path / "nowhere" / "registry.yaml")
    with pytest.raises(RegistryError, match="sopctl init"):
        registry.load()

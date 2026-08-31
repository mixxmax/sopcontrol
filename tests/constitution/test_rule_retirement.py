"""第六批：规则永久退出必须预览确认、原子写入且停止参与当前执法。"""
from __future__ import annotations

import re
import shutil

import pytest

from sopcontrol.cli import main
from sopcontrol.model import RuleStatus, active_rules
from sopcontrol.registry import Registry, RegistryError


def _work(tmp_path):
    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/ci-deploy", work)
    return work


def _preview_id(output: str) -> str:
    match = re.search(r"preview_id:\s*([0-9a-f]{16})", output)
    assert match, output
    return match.group(1)


def _add_replacement(work, *, rule_id="DEPLOY-NEW"):
    assert main([
        "rule", "add", str(work),
        "--id", rule_id,
        "--statement", "部署必须经过新的 deploy_gate",
        "--modality", "MUST",
        "--status", "accepted",
        "--scope", "ci.deploy",
        "--source-ref", "docs/sop.md",
        "--consumer-marker", "deploy_gate",
    ]) == 0


def test_deprecate_requires_matching_preview_and_updates_projection(tmp_path, capsys):
    work = _work(tmp_path)
    assert main(["project", "all", str(work)]) == 0
    capsys.readouterr()
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    before = registry.path.read_bytes()

    command = [
        "rule", "deprecate", "DEPLOY-001", str(work),
        "--reason", "部署入口已由平台结构保证替代",
        "--by", "human-reviewer",
    ]
    assert main(command) == 0
    preview_output = capsys.readouterr().out
    preview_id = _preview_id(preview_output)
    assert "受影响任务" in preview_output
    assert "投影目标: AGENTS.md, CLAUDE.md" in preview_output
    assert registry.path.read_bytes() == before

    assert main(command + ["--confirm-preview", preview_id]) == 0
    retired = registry.get("DEPLOY-001")
    assert retired.status == RuleStatus.deprecated
    assert retired.retirement_reason == "部署入口已由平台结构保证替代"
    assert retired.retired_by == "human-reviewer"
    assert retired.retirement_id == preview_id
    assert "DEPLOY-001" not in (work / "AGENTS.md").read_text(encoding="utf-8")
    assert "DEPLOY-001" not in (work / "CLAUDE.md").read_text(encoding="utf-8")

    after = registry.path.read_bytes()
    assert main(command + ["--confirm-preview", preview_id]) == 0
    assert registry.path.read_bytes() == after


def test_stale_preview_and_unknown_replacement_change_nothing(tmp_path, capsys):
    work = _work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    command = [
        "rule", "deprecate", "DEPLOY-001", str(work),
        "--reason", "旧流程退出",
        "--by", "human-reviewer",
    ]
    assert main(command) == 0
    preview_id = _preview_id(capsys.readouterr().out)
    _add_replacement(work, rule_id="UNRELATED")
    before = registry.path.read_bytes()
    assert main(command + ["--confirm-preview", preview_id]) == 2
    assert registry.path.read_bytes() == before

    assert main([
        "rule", "supersede", "DEPLOY-001", str(work),
        "--replacement", "DOES-NOT-EXIST",
        "--reason", "替代",
        "--by", "human-reviewer",
    ]) == 2
    assert registry.path.read_bytes() == before


def test_supersede_sets_both_sides_atomically_and_retired_rule_is_not_active(tmp_path, capsys):
    work = _work(tmp_path)
    _add_replacement(work)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    command = [
        "rule", "supersede", "DEPLOY-001", str(work),
        "--replacement", "DEPLOY-NEW",
        "--reason", "新规则接管部署入口",
        "--by", "human-reviewer",
    ]
    assert main(command) == 0
    preview_id = _preview_id(capsys.readouterr().out)
    assert main(command + ["--confirm-preview", preview_id]) == 0

    old = registry.get("DEPLOY-001")
    new = registry.get("DEPLOY-NEW")
    assert old.status == RuleStatus.superseded
    assert old.superseded_by == "DEPLOY-NEW"
    assert "DEPLOY-001" in new.supersedes
    assert {rule.rule_id for rule in active_rules(registry.load())}.isdisjoint({"DEPLOY-001"})

    from sopcontrol.audit import run_audit
    from plugins import DETECTORS, SENSORS

    report = run_audit(work, SENSORS, DETECTORS, persist=False)
    assert "DEPLOY-001" not in {verdict.rule_id for verdict in report.verdicts}
    assert "DEPLOY-001" not in {finding.rule_id for finding in report.findings}

    assert main([
        "task", "open", str(work),
        "--objective", "不得继续引用退休规则",
        "--allow", "scripts/deploy.py",
        "--require-rule", "DEPLOY-001",
        "--require-field", "status",
    ]) == 2


def test_supersede_atomically_accepts_proposed_conflicting_replacement(tmp_path, capsys):
    work = _work(tmp_path)
    assert main([
        "rule", "add", str(work),
        "--id", "DEPLOY-BAN",
        "--statement", "部署不得再经过旧 deploy_gate",
        "--modality", "MUST_NOT",
        "--status", "proposed",
        "--scope", "ci.deploy",
        "--source-ref", "docs/sop.md",
        "--consumer-marker", "deploy_gate",
    ]) == 0
    command = [
        "rule", "supersede", "DEPLOY-001", str(work),
        "--replacement", "DEPLOY-BAN",
        "--reason", "新策略原子接管",
        "--by", "human-reviewer",
    ]
    assert main(command) == 0
    preview_id = _preview_id(capsys.readouterr().out)
    assert main(command + ["--confirm-preview", preview_id]) == 0

    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    assert registry.get("DEPLOY-001").status == RuleStatus.superseded
    replacement = registry.get("DEPLOY-BAN")
    assert replacement.status == RuleStatus.accepted
    assert replacement.accepted_at is not None
    assert replacement.supersedes == ["DEPLOY-001"]


def test_retired_rule_cannot_create_repair_from_historical_finding(tmp_path, capsys):
    from plugins import DETECTORS, SENSORS
    from sopcontrol.audit import run_audit
    from sopcontrol.ledger import Ledger
    from sopcontrol.repair import RepairError, open_repair

    work = _work(tmp_path)
    run_audit(work, SENSORS, DETECTORS, persist=True)
    finding = next(
        finding
        for finding in Ledger(work / ".sopcontrol/evidence/ledger.jsonl").load_findings()
        if finding.rule_id == "DEPLOY-001"
    )
    command = [
        "rule", "deprecate", "DEPLOY-001", str(work),
        "--reason", "旧规则退出",
        "--by", "human-reviewer",
    ]
    assert main(command) == 0
    preview_id = _preview_id(capsys.readouterr().out)
    assert main(command + ["--confirm-preview", preview_id]) == 0

    with pytest.raises(RepairError, match="已永久退出"):
        open_repair(work, finding.finding_id, ["scripts/deploy.py"], SENSORS, DETECTORS)


def test_projection_failure_rolls_back_registry_and_projection_files(tmp_path, capsys, monkeypatch):
    work = _work(tmp_path)
    assert main(["project", "all", str(work)]) == 0
    capsys.readouterr()
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    command = [
        "rule", "deprecate", "DEPLOY-001", str(work),
        "--reason", "退出",
        "--by", "human-reviewer",
    ]
    assert main(command) == 0
    preview_id = _preview_id(capsys.readouterr().out)
    before = {
        registry.path: registry.path.read_bytes(),
        work / "AGENTS.md": (work / "AGENTS.md").read_bytes(),
        work / "CLAUDE.md": (work / "CLAUDE.md").read_bytes(),
    }

    import sopcontrol.project

    monkeypatch.setattr(sopcontrol.project, "write_all_projections", lambda root: (_ for _ in ()).throw(OSError("disk full")))
    assert main(command + ["--confirm-preview", preview_id]) == 2
    for path, content in before.items():
        assert path.read_bytes() == content


def test_registry_rejects_agent_retirement_and_invalid_source_state(tmp_path):
    work = _work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    with pytest.raises(RegistryError, match="人工"):
        registry.retirement_preview(
            "DEPLOY-001", action="deprecate", reason="退出", actor="agent"
        )
    rules = registry.load()
    proposed = next(rule for rule in rules if rule.rule_id == "DEPLOY-002")
    proposed.status = RuleStatus.proposed
    registry.save(rules)
    with pytest.raises(RegistryError, match="当前有效"):
        registry.retirement_preview(
            "DEPLOY-002", action="deprecate", reason="退出", actor="human"
        )

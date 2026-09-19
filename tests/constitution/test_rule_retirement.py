"""第六批：规则永久退出必须预览确认、原子写入且停止参与当前执法。"""
from __future__ import annotations

import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sopcontrol.cli import main
from sopcontrol.attest import record_attestation
from sopcontrol.bootstrap import check_orders
from sopcontrol.model import Modality, Rule, RuleStatus, SourceRef, active_rules
from sopcontrol.registry import Registry, RegistryError
from sopcontrol.task import TaskStatus, TaskStore


def _work(tmp_path):
    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/ci-deploy", work)
    return work


def _preview_id(output: str) -> str:
    match = re.search(r"preview_id:\s*([0-9a-f]{16})", output)
    assert match, output
    return match.group(1)


def _accepted_flags(work, rule_id: str, statement: str) -> list[str]:
    """accepted 写入必须附可信确认（测试内走统一原语）。"""
    from sopcontrol.confirmation import change_digest, request_confirmation
    from sopcontrol.learning import read_learning_confirmation_secret

    rec = request_confirmation(work, kind="rule-accept", subject_id=rule_id,
                               digest=change_digest(rule_id, statement),
                               purpose="test")
    secret = read_learning_confirmation_secret(work, rec["confirmation_id"])
    return ["--confirmation-id", rec["confirmation_id"],
            f"--confirmation-secret={secret}"]


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
    ] + _accepted_flags(work, rule_id, "部署必须经过新的 deploy_gate")) == 0


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
    agents = (work / "AGENTS.md").read_text(encoding="utf-8")
    claude = (work / "CLAUDE.md").read_text(encoding="utf-8")
    # 退休规则不得再进硬规则核；编年旅程仍可出现该 id
    for text in (agents, claude):
        hard = text.split("## 必须遵守的规则")[1].split("## ")[0] if "## 必须遵守的规则" in text else text
        assert "DEPLOY-001" not in hard

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


def test_projection_rollback_reports_restore_failures_truthfully(
    tmp_path, capsys, monkeypatch
):
    work = _work(tmp_path)
    assert main(["project", "all", str(work)]) == 0
    capsys.readouterr()
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    command = [
        "rule", "deprecate", "DEPLOY-001", str(work),
        "--reason", "回滚失败应如实报告",
        "--by", "human-reviewer",
    ]
    assert main(command) == 0
    preview_id = _preview_id(capsys.readouterr().out)

    import sopcontrol.project

    monkeypatch.setattr(
        sopcontrol.project,
        "write_all_projections",
        lambda root: (_ for _ in ()).throw(OSError("projection failed")),
    )
    original_write_bytes = Path.write_bytes

    def fail_registry_restore(path, content):
        if path == registry.path:
            raise OSError("registry restore failed")
        return original_write_bytes(path, content)

    monkeypatch.setattr(Path, "write_bytes", fail_registry_restore)

    assert main(command + ["--confirm-preview", preview_id]) == 2
    error = capsys.readouterr().err
    assert "未恢复" in error
    assert str(registry.path) in error
    assert "已回滚" not in error


def test_registry_rejects_agent_retirement_and_invalid_source_state(tmp_path):
    work = _work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    with pytest.raises(RegistryError, match="人工"):
        registry.retirement_preview(
            "DEPLOY-001", action="deprecate", reason="退出", actor="agent"
        )
    registry.add(Rule(
        rule_id="DEPLOY-PROPOSED",
        statement="尚未接受的规则不能永久退出",
        modality=Modality.MUST,
        status=RuleStatus.proposed,
        source=SourceRef(type="document", ref="docs/runbook.md"),
    ))
    with pytest.raises(RegistryError, match="当前有效"):
        registry.retirement_preview(
            "DEPLOY-PROPOSED", action="deprecate", reason="退出", actor="human"
        )


def _deprecate(work, capsys, rule_id="DEPLOY-001"):
    command = [
        "rule", "deprecate", rule_id, str(work),
        "--reason", "6R 回归测试退出",
        "--by", "human-reviewer",
    ]
    assert main(command) == 0
    preview_id = _preview_id(capsys.readouterr().out)
    assert main(command + ["--confirm-preview", preview_id]) == 0
    capsys.readouterr()


def test_retirement_states_have_only_the_governed_registry_entry(tmp_path, capsys):
    work = _work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    before = registry.path.read_bytes()

    for status in (RuleStatus.deprecated, RuleStatus.superseded):
        with pytest.raises(RegistryError, match="永久退出"):
            registry.transition("DEPLOY-001", status)
        assert registry.path.read_bytes() == before

        assert main([
            "rule", "add", str(work),
            "--id", f"DIRECT-{status.value.upper()}",
            "--statement", "不得绕过受治理退出入口",
            "--modality", "MUST",
            "--status", status.value,
            "--source-ref", "docs/runbook.md",
        ]) == 2
        assert "永久退出" in capsys.readouterr().err
        assert registry.path.read_bytes() == before


def test_public_save_rejects_active_rule_retirement_injection(tmp_path):
    work = _work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    original = [rule.model_dump(mode="json") for rule in registry.load()]

    for status in (RuleStatus.deprecated, RuleStatus.superseded):
        rules = registry.load()
        target = next(rule for rule in rules if rule.rule_id == "DEPLOY-001")
        target.status = status
        with pytest.raises(RegistryError, match="永久退出"):
            registry.save(rules)
        assert [rule.model_dump(mode="json") for rule in registry.load()] == original


def test_public_save_rejects_new_retired_record(tmp_path):
    work = _work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    original = [rule.model_dump(mode="json") for rule in registry.load()]
    rules = registry.load()
    rules.append(Rule(
        rule_id="DIRECT-RETIRED",
        statement="不得直接注入退休记录",
        modality=Modality.MUST,
        status=RuleStatus.deprecated,
        source=SourceRef(type="document", ref="docs/runbook.md"),
    ))

    with pytest.raises(RegistryError, match="永久退出"):
        registry.save(rules)
    assert [rule.model_dump(mode="json") for rule in registry.load()] == original


_RETIREMENT_FACT_MUTATIONS = (
    ("supersedes", ["DEPLOY-001"]),
    ("superseded_by", "DEPLOY-NEW"),
    ("retirement_reason", "普通写入伪造退出原因"),
    ("retired_by", "ordinary-writer"),
    ("retired_at", datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)),
    ("retirement_id", "forged-retirement-id"),
)


@pytest.mark.parametrize(("field", "value"), _RETIREMENT_FACT_MUTATIONS)
@pytest.mark.parametrize("operation", ("save", "add"))
def test_public_writes_reject_retirement_facts_on_new_active_rule(
    tmp_path, field, value, operation
):
    work = _work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    before = registry.path.read_bytes()
    rule = Rule(
        rule_id=f"FORGED-{field.upper()}",
        statement="新建 active 规则不得夹带退出治理事实",
        modality=Modality.MUST,
        status=RuleStatus.accepted,
        source=SourceRef(type="document", ref="docs/runbook.md"),
    )
    setattr(rule, field, value)

    with pytest.raises(RegistryError, match="退出治理事实"):
        if operation == "add":
            registry.add(rule)
        else:
            registry.save(registry.load() + [rule])

    assert registry.path.read_bytes() == before


@pytest.mark.parametrize(("field", "value"), _RETIREMENT_FACT_MUTATIONS)
def test_public_save_rejects_retirement_fact_changes_on_existing_active_rule(
    tmp_path, field, value
):
    work = _work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    before = registry.path.read_bytes()
    rules = registry.load()
    target = next(rule for rule in rules if rule.rule_id == "DEPLOY-001")
    setattr(target, field, value)

    with pytest.raises(RegistryError, match="退出治理事实"):
        registry.save(rules)

    assert registry.path.read_bytes() == before


def test_public_save_cannot_change_or_remove_historical_retirement(tmp_path, capsys):
    work = _work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    _deprecate(work, capsys)
    retired = registry.get("DEPLOY-001").model_dump(mode="json")

    mutations = []
    removed = [rule for rule in registry.load() if rule.rule_id != "DEPLOY-001"]
    mutations.append(removed)
    restored = registry.load()
    next(rule for rule in restored if rule.rule_id == "DEPLOY-001").status = RuleStatus.accepted
    mutations.append(restored)
    rewritten = registry.load()
    next(rule for rule in rewritten if rule.rule_id == "DEPLOY-001").statement = "改写历史"
    mutations.append(rewritten)

    for rules in mutations:
        with pytest.raises(RegistryError, match="历史退出记录"):
            registry.save(rules)
        assert registry.get("DEPLOY-001").model_dump(mode="json") == retired


def test_public_save_rejects_duplicate_id_before_retirement_validation(tmp_path, capsys):
    work = _work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    _deprecate(work, capsys)
    retired = registry.get("DEPLOY-001").model_dump(mode="json")
    rules = registry.load()
    original = next(rule for rule in rules if rule.rule_id == "DEPLOY-001")
    rewritten = original.model_copy(update={"statement": "重复项改写历史"})
    rules.extend([rewritten, original.model_copy(deep=True)])

    with pytest.raises(RegistryError, match="重复 rule_id: DEPLOY-001"):
        registry.save(rules)

    loaded = registry.load()
    assert len([rule for rule in loaded if rule.rule_id == "DEPLOY-001"]) == 1
    assert registry.get("DEPLOY-001").model_dump(mode="json") == retired


def test_public_save_preserves_unchanged_retirement_during_ordinary_update(tmp_path, capsys):
    work = _work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    _deprecate(work, capsys)
    retired = registry.get("DEPLOY-001").model_dump(mode="json")
    rules = registry.load()
    rules.append(Rule(
        rule_id="ORDINARY-NEW",
        statement="普通规则仍可登记",
        modality=Modality.MUST,
        status=RuleStatus.proposed,
        source=SourceRef(type="document", ref="docs/runbook.md"),
    ))

    registry.save(rules)

    assert registry.get("DEPLOY-001").model_dump(mode="json") == retired
    assert registry.get("ORDINARY-NEW").status == RuleStatus.proposed


def test_supersede_rejects_third_party_conflict_before_accepting_replacement(tmp_path, capsys):
    work = _work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    for rule_id, modality, status in (
        ("DEPLOY-BAN", "MUST_NOT", "proposed"),
        ("DEPLOY-GUARD", "MUST", "accepted"),
    ):
        assert main([
            "rule", "add", str(work),
            "--id", rule_id,
            "--statement", f"{rule_id} 部署策略",
            "--modality", modality,
            "--status", status,
            "--scope", "ci.deploy",
            "--source-ref", "docs/runbook.md",
            "--consumer-marker", "deploy_gate",
        ] + _accepted_flags(work, rule_id, f"{rule_id} 部署策略")) == 0
    capsys.readouterr()

    command = [
        "rule", "supersede", "DEPLOY-001", str(work),
        "--replacement", "DEPLOY-BAN",
        "--reason", "新规则接管",
        "--by", "human-reviewer",
    ]
    assert main(command) == 0
    preview_id = _preview_id(capsys.readouterr().out)
    before = registry.path.read_bytes()

    assert main(command + ["--confirm-preview", preview_id]) == 2
    assert registry.path.read_bytes() == before
    assert registry.get("DEPLOY-001").status == RuleStatus.accepted
    replacement = registry.get("DEPLOY-BAN")
    assert replacement.status == RuleStatus.proposed
    assert replacement.supersedes == []


def test_retired_attestation_does_not_satisfy_governance_maturity(tmp_path, capsys):
    work = _work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    record_attestation(
        work,
        "DEPLOY-001",
        bypass_note="仅允许经过受控部署入口",
        by="human-reviewer",
    )

    before = {item["order_id"]: item for item in check_orders(work, registry.load())}
    assert before["ORDER-5"]["satisfied"] is True

    _deprecate(work, capsys)
    after = {item["order_id"]: item for item in check_orders(work, registry.load())}
    assert after["ORDER-5"]["satisfied"] is False


def test_task_accept_rejects_rule_retired_after_contract_creation(tmp_path, capsys):
    work = _work(tmp_path)
    assert main([
        "task", "open", str(work),
        "--objective", "验证退休后的任务迁移",
        "--allow", "scripts/deploy.py",
        "--require-rule", "DEPLOY-001",
        "--require-field", "status",
    ]) == 0
    task_id = TaskStore(work).list_all()[-1].task_id
    capsys.readouterr()

    _deprecate(work, capsys)
    assert main(["task", "accept", task_id, str(work)]) == 0
    output = capsys.readouterr().out
    task = TaskStore(work).load(task_id)
    assert task.status == TaskStatus.contract_proposed
    assert task.history[-1].allowed is False
    assert "引用了不存在的规则: DEPLOY-001" in output


def test_concurrent_retirement_confirmation_cannot_restore_retired_history(
    tmp_path, monkeypatch
):
    work = _work(tmp_path)
    registry_a = Registry(work / ".sopcontrol/rules/registry.yaml")
    registry_b = Registry(work / ".sopcontrol/rules/registry.yaml")
    preview_a = registry_a.retirement_preview(
        "DEPLOY-001", action="deprecate", reason="并发退出 A", actor="human-reviewer"
    )["preview_id"]
    preview_b = registry_b.retirement_preview(
        "ROLLBACK-001", action="deprecate", reason="并发退出 B", actor="human-reviewer"
    )["preview_id"]

    first_at_write = threading.Event()
    release_first = threading.Event()
    second_done = threading.Event()
    original_write = Registry._write

    def controlled_write(self, rules):
        if threading.current_thread().name == "retire-a":
            first_at_write.set()
            assert release_first.wait(timeout=5)
        original_write(self, rules)

    monkeypatch.setattr(Registry, "_write", controlled_write)
    results = []
    errors = []

    def confirm(registry, rule_id, reason, preview_id, done=None):
        try:
            registry.confirm_retirement(
                rule_id,
                action="deprecate",
                reason=reason,
                actor="human-reviewer",
                preview_id=preview_id,
            )
            results.append(rule_id)
        except Exception as exc:  # 线程中的异常必须回传主测试断言
            errors.append(exc)
        finally:
            if done is not None:
                done.set()

    thread_a = threading.Thread(
        target=confirm,
        name="retire-a",
        args=(registry_a, "DEPLOY-001", "并发退出 A", preview_a),
    )
    thread_a.start()
    assert first_at_write.wait(timeout=5)

    thread_b = threading.Thread(
        target=confirm,
        name="retire-b",
        args=(registry_b, "ROLLBACK-001", "并发退出 B", preview_b, second_done),
    )
    thread_b.start()
    second_done.wait(timeout=0.5)
    release_first.set()
    thread_a.join(timeout=5)
    thread_b.join(timeout=5)

    assert not thread_a.is_alive() and not thread_b.is_alive()
    assert results == ["DEPLOY-001"]
    assert len(errors) == 1
    assert isinstance(errors[0], RegistryError)
    assert "preview_id 已失效" in str(errors[0])
    assert registry_a.get("DEPLOY-001").status == RuleStatus.deprecated
    assert registry_a.get("ROLLBACK-001").status == RuleStatus.accepted


def test_projection_rollback_does_not_erase_concurrent_registry_write(
    tmp_path, monkeypatch
):
    work = _work(tmp_path)
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    preview_id = registry.retirement_preview(
        "DEPLOY-001",
        action="deprecate",
        reason="投影失败回滚",
        actor="human-reviewer",
    )["preview_id"]
    projection_started = threading.Event()
    release_projection = threading.Event()
    add_done = threading.Event()
    results = {}

    def fail_projection(root):
        projection_started.set()
        assert release_projection.wait(timeout=5)
        raise OSError("projection failed")

    import sopcontrol.project

    monkeypatch.setattr(sopcontrol.project, "write_all_projections", fail_projection)

    def retire():
        results["retire"] = main([
            "rule", "deprecate", "DEPLOY-001", str(work),
            "--reason", "投影失败回滚",
            "--by", "human-reviewer",
            "--confirm-preview", preview_id,
        ])

    def add_rule():
        try:
            Registry(work / ".sopcontrol/rules/registry.yaml").add(Rule(
                rule_id="CONCURRENT-ADD",
                statement="并发合法写入不得被回滚抹除",
                modality=Modality.MUST,
                status=RuleStatus.proposed,
                source=SourceRef(type="document", ref="docs/runbook.md"),
            ))
            results["add"] = "ok"
        finally:
            add_done.set()

    retire_thread = threading.Thread(target=retire, name="retire-with-projection")
    retire_thread.start()
    assert projection_started.wait(timeout=5)

    add_thread = threading.Thread(target=add_rule, name="concurrent-add")
    add_thread.start()
    add_done.wait(timeout=0.5)
    blocked_during_projection = not add_done.is_set()
    release_projection.set()
    retire_thread.join(timeout=5)
    add_thread.join(timeout=5)

    assert not retire_thread.is_alive() and not add_thread.is_alive()
    assert blocked_during_projection is True
    assert results == {"retire": 2, "add": "ok"}
    assert registry.get("DEPLOY-001").status == RuleStatus.accepted
    assert registry.get("CONCURRENT-ADD").status == RuleStatus.proposed


def test_registry_aliases_share_the_same_cross_process_lock(tmp_path):
    work = _work(tmp_path)
    alias = tmp_path / "work-alias"
    alias.symlink_to(work, target_is_directory=True)

    canonical = Registry(work / ".sopcontrol/rules/registry.yaml")
    through_alias = Registry(alias / ".sopcontrol/rules/registry.yaml")

    assert canonical.path.resolve() == through_alias.path.resolve()
    assert canonical._lock_path() == through_alias._lock_path()


def test_attestation_transaction_preserves_concurrent_registry_add(tmp_path, monkeypatch):
    work = _work(tmp_path)
    attest_at_save = threading.Event()
    release_attest = threading.Event()
    add_done = threading.Event()
    errors = []
    original_write = Registry._write

    def controlled_write(self, rules):
        if threading.current_thread().name == "attest-rule":
            attest_at_save.set()
            assert release_attest.wait(timeout=5)
        return original_write(self, rules)

    monkeypatch.setattr(Registry, "_write", controlled_write)

    def attest_rule():
        try:
            record_attestation(
                work,
                "DEPLOY-001",
                bypass_note="部署入口仍需防止直连绕过",
                by="human-reviewer",
            )
        except Exception as exc:
            errors.append(exc)

    def add_rule():
        try:
            Registry(work / ".sopcontrol/rules/registry.yaml").add(Rule(
                rule_id="CONCURRENT-ATTEST-ADD",
                statement="并发新增规则不得被确认书旧快照覆盖",
                modality=Modality.MUST,
                status=RuleStatus.proposed,
                source=SourceRef(type="document", ref="docs/runbook.md"),
            ))
        except Exception as exc:
            errors.append(exc)
        finally:
            add_done.set()

    attest_thread = threading.Thread(target=attest_rule, name="attest-rule")
    attest_thread.start()
    assert attest_at_save.wait(timeout=5)

    add_thread = threading.Thread(target=add_rule, name="concurrent-attest-add")
    add_thread.start()
    add_done.wait(timeout=0.5)
    blocked_during_attestation = not add_done.is_set()
    release_attest.set()
    attest_thread.join(timeout=5)
    add_thread.join(timeout=5)

    assert not attest_thread.is_alive() and not add_thread.is_alive()
    assert blocked_during_attestation is True
    assert errors == []
    registry = Registry(work / ".sopcontrol/rules/registry.yaml")
    assert registry.get("DEPLOY-001").attested_by == "human-reviewer"
    assert registry.get("CONCURRENT-ATTEST-ADD").status == RuleStatus.proposed


def test_retired_rule_no_longer_blocks_opposite_replacement_rule(tmp_path, capsys):
    work = _work(tmp_path)
    _deprecate(work, capsys)

    assert main([
        "rule", "add", str(work),
        "--id", "DEPLOY-OPPOSITE",
        "--statement", "部署不得再经过旧 deploy_gate",
        "--modality", "MUST_NOT",
        "--status", "accepted",
        "--scope", "ci.deploy",
        "--source-ref", "docs/runbook.md",
        "--consumer-marker", "deploy_gate",
    ] + _accepted_flags(work, "DEPLOY-OPPOSITE", "部署不得再经过旧 deploy_gate")) == 0
    assert Registry(work / ".sopcontrol/rules/registry.yaml").get(
        "DEPLOY-OPPOSITE"
    ).status == RuleStatus.accepted

"""宪法测试：任务迁移门是纯函数、拒绝必可解释、路径规范化拒绝上跳。"""
import builtins
from datetime import datetime, timedelta, timezone
import shutil

from sopcontrol.audit import run_audit
from sopcontrol.bootstrap import MATURITY_KIND
from sopcontrol.model import effective_rules
from sopcontrol.registry import Registry
from sopcontrol.task import (
    Contract,
    TaskRecord,
    TaskStatus,
    evaluate_transition,
    normalize_relpath,
    path_allowed,
)


def make_task(**overrides) -> TaskRecord:
    base = dict(
        task_id="TASK-0001",
        contract=Contract(
            objective="接线规则",
            allowed_writes=["src"],
            required_rules=["R-1"],
        ),
        status=TaskStatus.contract_proposed,
    )
    base.update(overrides)
    return TaskRecord(**base)


def test_transition_gate_does_no_io(monkeypatch):
    def no_open(*args, **kwargs):
        raise AssertionError("迁移门不得做任何 I/O（宪法：纯函数）")

    monkeypatch.setattr(builtins, "open", no_open)
    decision = evaluate_transition(
        make_task(), "accept", known_rule_ids={"R-1"}
    )
    assert decision.allowed and decision.to_status == TaskStatus.executing


def test_rejections_are_explainable():
    cases = [
        (make_task(status=TaskStatus.executing), "accept", {}),
        (make_task(status=TaskStatus.executing), "submit", {"changed_paths": []}),
        (make_task(status=TaskStatus.executing), "deliver", {}),
        (make_task(status=TaskStatus.contract_proposed), "未知动作", {}),
    ]
    for task, action, kwargs in cases:
        decision = evaluate_transition(task, action, known_rule_ids={"R-1"}, **kwargs)
        assert not decision.allowed
        assert decision.reason.strip() and decision.next_action.strip()


def test_contract_without_completion_definition_is_rejected():
    task = make_task(contract=Contract(objective="x", allowed_writes=["src"], required_rules=[]))
    decision = evaluate_transition(task, "accept", known_rule_ids=set())
    assert not decision.allowed
    assert "required_rules" in decision.reason


def test_accept_rejects_allowed_writes_outside_required_rule_scope():
    task = make_task(
        contract=Contract(
            objective="接线规则",
            allowed_writes=["src", "docs"],
            required_rules=["R-1"],
        )
    )
    decision = evaluate_transition(
        task,
        "accept",
        known_rule_ids={"R-1"},
        rule_scopes={"R-1": ["src"]},
    )
    assert not decision.allowed
    assert "docs" in decision.reason and "scope" in decision.reason


def test_accept_keeps_project_scope_compatible():
    decision = evaluate_transition(
        make_task(),
        "accept",
        known_rule_ids={"R-1"},
        rule_scopes={"R-1": []},
    )
    assert decision.allowed


def test_unknown_rule_reference_is_rejected():
    decision = evaluate_transition(make_task(), "accept", known_rule_ids={"OTHER"})
    assert not decision.allowed
    assert "R-1" in decision.reason


def test_verifier_self_approval_guard():
    """场景6：控制器路径改动未提交基线 → blocked；已干净 → 正常裁决。"""
    task = make_task()
    task.status = TaskStatus.verification_pending
    task.changed_paths = ["plugins/detectors/evil.py"]
    task.contract = Contract(
        objective="接线规则", allowed_writes=["plugins"],
        required_rules=["R-1"],
    )

    dirty = evaluate_transition(
        task, "verify",
        rule_verdicts={"R-1": "pass"},
        controller_dirty=["plugins/detectors/evil.py"],
    )
    assert dirty.to_status == TaskStatus.blocked
    assert "9.3" in dirty.reason and "基线" in dirty.next_action

    clean = evaluate_transition(
        task, "verify",
        rule_verdicts={"R-1": "pass"},
        controller_dirty=[],
    )
    assert clean.to_status == TaskStatus.verified


def _pending_task() -> TaskRecord:
    task = make_task()
    task.status = TaskStatus.verification_pending
    return task


def test_failing_test_run_blocks_even_when_rules_pass():
    """E4 是独立事实：没有任何规则消费它，跑挂的测试也必须拦住完成门。"""
    decision = evaluate_transition(
        _pending_task(), "verify",
        rule_verdicts={"R-1": "pass"},
        test_run={
            "command": ".venv/bin/pytest -q",
            "passed": False,
            "exit_code": 1,
            "output_tail": "1 failed, 3 passed in 0.20s",
        },
    )
    assert decision.to_status == TaskStatus.repair_required
    assert decision.repair_count == 1
    assert "E4" in decision.reason and ".venv/bin/pytest -q" in decision.reason
    assert "1 failed" in decision.reason


def test_failing_test_run_exhausts_repair_budget():
    task = _pending_task()
    task.repair_count = task.contract.max_repairs
    decision = evaluate_transition(
        task, "verify",
        rule_verdicts={"R-1": "pass"},
        test_run={"command": "pytest", "passed": False, "exit_code": 1},
    )
    assert decision.to_status == TaskStatus.failed_unverified
    assert "预算耗尽" in decision.reason


def test_passing_test_run_reports_e4_not_e3():
    decision = evaluate_transition(
        _pending_task(), "verify",
        rule_verdicts={"R-1": "pass"},
        test_run={
            "command": ".venv/bin/pytest -q",
            "passed": True,
            "exit_code": 0,
            "duration_seconds": 1.57,
        },
    )
    assert decision.to_status == TaskStatus.verified
    assert "E4" in decision.reason and ".venv/bin/pytest -q" in decision.reason
    # E4 与 E3 并存是对的（实测 + 独立审计）；不许出现的是「本轮没跑测试」这句
    assert "未执行测试命令" not in decision.reason


def test_absent_test_run_stays_honest_about_e3():
    """没跑测试就不许自称 E4——少报可以，虚报不行。"""
    decision = evaluate_transition(
        _pending_task(), "verify", rule_verdicts={"R-1": "pass"},
    )
    assert decision.to_status == TaskStatus.verified
    assert "E3" in decision.reason
    assert "E4" not in decision.reason


def test_e4_gate_stays_pure(monkeypatch):
    def no_open(*args, **kwargs):
        raise AssertionError("迁移门不得做任何 I/O（宪法：纯函数）")

    monkeypatch.setattr(builtins, "open", no_open)
    decision = evaluate_transition(
        _pending_task(), "verify",
        rule_verdicts={"R-1": "pass"},
        test_run={"command": "pytest", "passed": False, "exit_code": 2},
    )
    assert decision.to_status == TaskStatus.repair_required


def test_path_normalization_rejects_escape_attempts():
    for bad in ["/etc/passwd", "../outside.py", "src/../../escape.py"]:
        assert path_allowed(bad, ["src"]) is False
    assert path_allowed("src/a/b.py", ["src"]) is True
    assert path_allowed("src", ["src"]) is True
    assert path_allowed("srcevil.py", ["src"]) is False  # 前缀必须落在路径边界上


def test_file_granularity_uses_exact_paths_not_filename_shapes():
    assert path_allowed("src.v2", ["src.v2"], write_granularity="file") is True
    assert path_allowed("src.v2/secret.py", ["src.v2"], write_granularity="file") is False
    assert path_allowed("Makefile", ["Makefile"], write_granularity="file") is True
    assert path_allowed("Dockerfile", ["Dockerfile"], write_granularity="file") is True


def test_prefix_granularity_keeps_directory_scope():
    assert path_allowed("src/a.py", ["src"], write_granularity="prefix") is True


def test_submit_rechecks_current_required_rule_scope():
    task = make_task(status=TaskStatus.executing)
    decision = evaluate_transition(
        task,
        "submit",
        changed_paths=["src/app.py"],
        known_rule_ids={"R-1"},
        rule_scopes={"R-1": ["docs"]},
    )
    assert not decision.allowed
    assert "src" in decision.reason and "scope" in decision.reason


def test_verify_rechecks_current_required_rule_scope_fail_closed():
    task = _pending_task()
    task.changed_paths = ["src/app.py"]
    decision = evaluate_transition(
        task,
        "verify",
        rule_verdicts={"R-1": "pass"},
        known_rule_ids=set(),
        rule_scopes={},
    )
    assert decision.to_status == TaskStatus.blocked
    assert "R-1" in decision.reason and "effective" in decision.reason


def test_run_audit_uses_one_fixed_time_for_verdicts_and_maturity(tmp_path):
    work = tmp_path / "project"
    shutil.copytree("corpus/fixtures/jobflow-preview", work)
    registry = Registry(work / ".sopcontrol" / "rules" / "registry.yaml")
    until = datetime.now(timezone.utc) + timedelta(hours=1)
    active = effective_rules(registry.load(), at=until - timedelta(hours=2))
    active_ids = [rule.rule_id for rule in active]
    for rule in active:
        params = {
            "action": "suspend",
            "reason": "fixed audit boundary",
            "actor": "test-human",
            "until": until,
        }
        preview = registry.lifecycle_preview(rule.rule_id, **params)
        registry.confirm_lifecycle(
            rule.rule_id, preview_id=preview["preview_id"], **params
        )

    before = run_audit(work, [], [], at=until - timedelta(seconds=1))
    after = run_audit(work, [], [], at=until + timedelta(seconds=1))

    before_maturity = next(
        evidence for evidence in before.evidence if evidence.kind == MATURITY_KIND
    )
    after_maturity = next(
        evidence for evidence in after.evidence if evidence.kind == MATURITY_KIND
    )
    before_l1 = next(
        order for order in before_maturity.observed["orders"] if order["rung"] == "L1"
    )
    after_l1 = next(
        order for order in after_maturity.observed["orders"] if order["rung"] == "L1"
    )

    assert [verdict.rule_id for verdict in before.verdicts] == []
    assert [verdict.rule_id for verdict in after.verdicts] == active_ids
    assert before_l1["satisfied"] is False
    assert after_l1["satisfied"] is True

"""对话中途换模型：harness 自动校验执行者身份。"""
from __future__ import annotations

import json
from pathlib import Path

from sopcontrol.cli import main
from sopcontrol.harness import (
    GUARD_EXECUTOR_IDENTITY,
    check_tool_call,
    extract_claimed_model,
)
from sopcontrol.model import Modality, Rule, RuleStatus, SourceRef
from sopcontrol.registry import Registry
from sopcontrol.task import (
    Contract,
    TaskRecord,
    TaskStatus,
    TaskStore,
    active_bound_executor,
)


def test_extract_claimed_model_variants():
    assert extract_claimed_model({"model": "m1"}) == "m1"
    assert extract_claimed_model({"session": {"model_id": "m2"}}) == "m2"
    assert extract_claimed_model({"tool_input": {"model": "m3"}}) == "m3"
    assert extract_claimed_model({"tool_name": "Edit"}) == ""


def test_mismatch_denies_write():
    d = check_tool_call(
        {"tool_name": "Edit", "tool_input": {"file_path": "src/a.py"}, "model": "new"},
        bound_executor="old",
        claimed_model="new",
    )
    assert d.permissionDecision == "deny"
    assert GUARD_EXECUTOR_IDENTITY in d.rule_ids
    assert "rebind" in d.reason


def test_match_allows_write():
    d = check_tool_call(
        {"tool_name": "Write", "tool_input": {"file_path": "src/a.py", "content": "x"}, "model": "same"},
        bound_executor="same",
        claimed_model="same",
    )
    assert d.permissionDecision == "allow"
    assert GUARD_EXECUTOR_IDENTITY in d.rule_ids


def test_no_claimed_model_keeps_compat():
    """载荷未声明模型时不因绑定执行者而拦——兼容旧 harness。"""
    d = check_tool_call(
        {"tool_name": "Edit", "tool_input": {"file_path": "src/a.py"}},
        bound_executor="old",
        claimed_model="",
    )
    assert d.permissionDecision == "allow"


def test_read_not_blocked_on_mismatch():
    d = check_tool_call(
        {"tool_name": "Read", "tool_input": {"file_path": "src/a.py"}, "model": "new"},
        bound_executor="old",
        claimed_model="new",
    )
    assert d.permissionDecision == "allow"


def test_active_bound_executor_picks_latest():
    tasks = [
        TaskRecord(
            task_id="TASK-0001",
            contract=Contract(objective="a", model_identity="old"),
            status=TaskStatus.executing,
        ),
        TaskRecord(
            task_id="TASK-0002",
            contract=Contract(objective="b", model_identity="new"),
            status=TaskStatus.repair_required,
        ),
    ]
    # updated_at 默认接近；用 task_id 次序兜底时取 max
    assert active_bound_executor(tasks) in {"old", "new"}
    assert active_bound_executor([]) == ""
    assert active_bound_executor([
        TaskRecord(
            task_id="TASK-0003",
            contract=Contract(objective="c"),
            status=TaskStatus.executing,
        )
    ]) == ""


def test_harness_check_cli_denies_mismatch(tmp_path, capsys):
    root = tmp_path / "proj"
    (root / ".sopcontrol" / "rules").mkdir(parents=True)
    (root / ".sopcontrol" / "tasks").mkdir(parents=True)
    Registry(root / ".sopcontrol" / "rules" / "registry.yaml").save([
        Rule(
            rule_id="R-1",
            statement="must",
            modality=Modality.MUST,
            status=RuleStatus.accepted,
            source=SourceRef(type="manual_seed", ref="t"),
            consumer_markers=["g"],
        )
    ])
    TaskStore(root).save(TaskRecord(
        task_id="TASK-0001",
        contract=Contract(
            objective="work",
            allowed_writes=["src/a.py"],
            required_rules=["R-1"],
            model_identity="bound-model",
        ),
        status=TaskStatus.executing,
    ))
    payload = json.dumps({
        "tool_name": "Edit",
        "tool_input": {"file_path": "src/a.py"},
        "model": "other-model",
    })
    # harness-check 打印 JSON 到 stdout，退出码仍 0（决策在 JSON 里）
    assert main(["harness-check", str(root), "--payload", payload]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    decision = out.get("hookSpecificOutput") or out
    assert decision.get("permissionDecision") == "deny"
    reason = decision.get("permissionDecisionReason") or decision.get("reason") or ""
    assert "rebind" in reason

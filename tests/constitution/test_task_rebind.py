"""对话中途换模型：rebind 只收紧，不继承旧放宽。"""
from __future__ import annotations

from pathlib import Path

import pytest

from sopcontrol.chronicle import load_project_events
from sopcontrol.cli import main
from sopcontrol.model import Modality, Rule, RuleStatus, SourceRef
from sopcontrol.registry import Registry
from sopcontrol.task import (
    Contract,
    RebindError,
    TaskRecord,
    TaskStatus,
    TaskStore,
    assert_executor_matches,
    rebind_executor,
    stricter_write_granularity,
)


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / ".sopcontrol" / "rules").mkdir(parents=True)
    (root / ".sopcontrol" / "tasks").mkdir(parents=True)
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x=1\n", encoding="utf-8")
    Registry(root / ".sopcontrol" / "rules" / "registry.yaml").save([
        Rule(
            rule_id="R-1",
            statement="must",
            modality=Modality.MUST,
            status=RuleStatus.accepted,
            source=SourceRef(type="manual_seed", ref="t"),
            consumer_markers=["gate"],
        )
    ])
    return root


def _strong_task(root: Path) -> TaskRecord:
    store = TaskStore(root)
    task = TaskRecord(
        task_id="TASK-0001",
        contract=Contract(
            objective="do work",
            allowed_writes=["src/a.py"],
            required_rules=["R-1"],
            max_repairs=2,
            write_granularity="prefix",
            strict_schema=False,
            model_identity="model-strong",
            capability_note="tier=strong",
        ),
        status=TaskStatus.executing,
    )
    store.save(task)
    return store.load("TASK-0001")


def test_stricter_granularity():
    assert stricter_write_granularity("prefix", "file") == "file"
    assert stricter_write_granularity("file", "prefer_file") == "file"
    assert stricter_write_granularity("prefix", "prefer_file") == "prefer_file"


def test_rebind_strong_to_unknown_tightens(tmp_path):
    root = _init(tmp_path)
    store = TaskStore(root)
    task = _strong_task(root)
    rebound = rebind_executor(
        store,
        task,
        new_model="model-unknown",
        knobs_max_repairs=1,
        knobs_write_granularity="file",
        knobs_strict_schema=True,
        knobs_tier="unknown",
        capability_note="无画像",
        root=root,
    )
    assert rebound.contract.model_identity == "model-unknown"
    assert rebound.contract.max_repairs == 1
    assert rebound.contract.write_granularity == "file"
    assert rebound.contract.strict_schema is True
    assert rebound.revision == 2
    assert any(e.action == "rebind" for e in rebound.history)
    kinds = [e.kind for e in load_project_events(root).events]
    assert "task.rebind" in kinds


def test_rebind_never_widens_repairs(tmp_path):
    root = _init(tmp_path)
    store = TaskStore(root)
    task = _strong_task(root)
    task.contract.max_repairs = 1
    task.revision += 1
    store.save(task)
    task = store.load("TASK-0001")
    rebound = rebind_executor(
        store,
        task,
        new_model="other",
        knobs_max_repairs=2,  # 新画像若更宽，仍不得抬高
        knobs_write_granularity="prefix",
        knobs_strict_schema=False,
        knobs_tier="strong",
        capability_note="strong",
        root=root,
    )
    assert rebound.contract.max_repairs == 1
    assert rebound.contract.write_granularity == "prefix"  # 旧已是 prefix，新也是
    assert rebound.contract.strict_schema is False


def test_rebind_rejects_file_granularity_with_directory_allows(tmp_path):
    root = _init(tmp_path)
    store = TaskStore(root)
    task = _strong_task(root)
    task.contract.allowed_writes = ["src"]
    task.revision += 1
    store.save(task)
    task = store.load("TASK-0001")
    with pytest.raises(RebindError, match="目录"):
        rebind_executor(
            store,
            task,
            new_model="weak-model",
            knobs_max_repairs=1,
            knobs_write_granularity="file",
            knobs_strict_schema=True,
            knobs_tier="weak",
            capability_note="weak",
            root=root,
        )


@pytest.mark.parametrize("terminal_status", [TaskStatus.delivered, TaskStatus.withdrawn])
def test_rebind_rejects_terminal(tmp_path, terminal_status):
    root = _init(tmp_path)
    store = TaskStore(root)
    task = _strong_task(root)
    task.status = terminal_status
    task.revision += 1
    store.save(task)
    with pytest.raises(RebindError, match="终态"):
        rebind_executor(
            store,
            store.load("TASK-0001"),
            new_model="x",
            knobs_max_repairs=1,
            knobs_write_granularity="file",
            knobs_strict_schema=True,
            knobs_tier="unknown",
            capability_note="n",
            root=root,
        )


def test_submit_model_mismatch_fails(tmp_path):
    root = _init(tmp_path)
    _strong_task(root)
    assert main([
        "task", "submit", "TASK-0001",
        "--changed", "src/a.py",
        "--model", "someone-else",
        str(root),
    ]) == 2


def test_cli_rebind_unknown(tmp_path):
    root = _init(tmp_path)
    _strong_task(root)
    # 无批准 live 画像 → unknown 旋钮
    assert main(["task", "rebind", "TASK-0001", "--model", "fresh-model", str(root)]) == 0
    task = TaskStore(root).load("TASK-0001")
    assert task.contract.model_identity == "fresh-model"
    assert task.contract.max_repairs == 1
    assert task.contract.write_granularity == "file"
    assert task.contract.strict_schema is True


def test_assert_executor_matches():
    task = TaskRecord(
        task_id="T",
        contract=Contract(
            objective="o",
            model_identity="a",
        ),
    )
    assert_executor_matches(task, None)
    assert_executor_matches(task, "a")
    with pytest.raises(RebindError):
        assert_executor_matches(task, "b")

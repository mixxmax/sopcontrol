"""场景13：同一项目两会话并发写状态——旧 revision 不得覆盖新状态。"""
import pytest

from sopcontrol.task import (
    Contract,
    TaskRecord,
    TaskStatus,
    TaskStore,
    evaluate_transition,
)


def test_scenario13_stale_session_cannot_overwrite(tmp_path):
    store = TaskStore(tmp_path)
    task = TaskRecord(
        task_id="TASK-0001",
        contract=Contract(
            objective="x", allowed_writes=["src"], required_rules=["R-1"],
        ),
    )
    store.save(task)

    # 两会话各自持有 r1 快照
    session_a = store.load("TASK-0001")
    session_b = store.load("TASK-0001")
    assert session_a.revision == session_b.revision == 1

    d_a = evaluate_transition(session_a, "accept", known_rule_ids={"R-1"})
    store.apply(session_a, d_a, "accept")
    assert store.load("TASK-0001").revision == 2
    assert store.load("TASK-0001").status == TaskStatus.executing

    # 会话 B 仍基于 r1 推进 → 必须拒绝覆盖
    d_b = evaluate_transition(session_b, "accept", known_rule_ids={"R-1"})
    with pytest.raises(RuntimeError, match="revision 冲突"):
        store.apply(session_b, d_b, "accept")

    # 磁盘状态仍是会话 A 的结果
    final = store.load("TASK-0001")
    assert final.revision == 2 and final.status == TaskStatus.executing

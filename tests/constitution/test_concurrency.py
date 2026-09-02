"""场景13：同一项目两会话并发写状态——旧 revision 不得覆盖新状态。"""
import threading

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


def test_task_store_compare_and_save_allows_only_one_concurrent_writer(tmp_path):
    """两个真实并发写者基于同一 revision 时，只能有一个提交成功。"""
    double_writes = []
    for round_number in range(12):
        root = tmp_path / f"round-{round_number}"
        store = TaskStore(root)
        original = TaskRecord(
            task_id="TASK-0001",
            contract=Contract(
                objective="x",
                allowed_writes=["src"],
                required_rules=["R-1"],
            ),
        )
        store.save(original)

        snapshots = [store.load("TASK-0001"), store.load("TASK-0001")]
        for snapshot in snapshots:
            snapshot.revision = 2
        start = threading.Barrier(3)
        outcomes: list[str] = []

        def save(snapshot):
            start.wait()
            try:
                store.save(snapshot, expected_revision=1)
            except RuntimeError:
                outcomes.append("conflict")
            else:
                outcomes.append("saved")

        threads = [threading.Thread(target=save, args=(snapshot,)) for snapshot in snapshots]
        for thread in threads:
            thread.start()
        start.wait()
        for thread in threads:
            thread.join(timeout=5)

        assert all(not thread.is_alive() for thread in threads)
        if outcomes.count("saved") == 2:
            double_writes.append(round_number)
        assert store.load("TASK-0001").revision == 2

    assert not double_writes, f"同一 revision 被并发写入两次: {double_writes}"

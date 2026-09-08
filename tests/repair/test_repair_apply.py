"""自动修复者 + worktree：注入 runner，不烧 token。"""
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit
from sopcontrol.cli import main
from sopcontrol.registry import Registry
from sopcontrol.repair import RepairError, apply_repair, open_repair
from sopcontrol.task import TaskStatus, TaskStore
from sopcontrol.worktree import WorktreeError, worktree_path


def test_apply_repair_merges_allowed_paths_only(tmp_path):
    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/shop-checkout", work)
    # need git for worktree
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=work, check=True, timeout=60)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=work, check=True, timeout=60)
    subprocess.run(["git", "config", "user.name", "t"], cwd=work, check=True, timeout=60)
    subprocess.run(["git", "add", "-A"], cwd=work, check=True, timeout=60)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=work, check=True, timeout=60)

    run_audit(work, SENSORS, DETECTORS, persist=True, compact=True)
    from sopcontrol.ledger import Ledger
    findings = Ledger(work / ".sopcontrol/evidence/ledger.jsonl").load_findings()
    fn = next(f for f in findings if f.pattern_id == "schema_field_unread")
    task = open_repair(work, fn.finding_id, ["src"], SENSORS, DETECTORS)
    store = TaskStore(work)
    # accept so status executing
    from sopcontrol.task import evaluate_transition
    d = evaluate_transition(task, "accept", known_rule_ids={fn.rule_id})
    store.apply(task, d, "accept")
    task = store.load(task.task_id)

    def runner(wt: Path, prompt: str):
        # 契约内改动
        (wt / "src" / "reporting.py").write_text(
            (wt / "src" / "reporting.py").read_text() + "\nx = schema_extra_field\n",
            encoding="utf-8",
        )
        # 契约外改动应被丢弃
        (wt / "docs" / "sop.md").write_text("HACK\n", encoding="utf-8")

    result = apply_repair(work, task.task_id, runner=runner)
    assert "src/reporting.py" in result["copied"]
    assert "docs/sop.md" in result["rejected_out_of_contract"]
    assert "schema_extra_field" in (work / "src" / "reporting.py").read_text()
    assert (work / "docs" / "sop.md").read_text() != "HACK\n"


def test_apply_repair_rejects_symlink_escaping_worktree(tmp_path):
    """symlink 逃逸必须在合并回主树前被拦住（R8 的接线证据）。

    `src/evil.py -> 仓库外文件` 过得了契约字符串层：路径确实以 src/ 开头。
    只有解析 symlink 才看得出它指向隔离树之外，而 copy2 是跟链接的——
    漏了这一层，隔离树里的一个软链接就能把外部内容搬进主树。
    这个用例断的是「resolves_inside 真的接在 apply_repair 的合并路径上」，
    不是这个函数自己的行为（那部分在 test_path_escape.py）。
    """
    import subprocess

    from sopcontrol.ledger import Ledger
    from sopcontrol.task import evaluate_transition

    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/shop-checkout", work)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True, timeout=60)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=work, check=True, timeout=60)
    subprocess.run(["git", "config", "user.name", "t"], cwd=work, check=True, timeout=60)
    subprocess.run(["git", "add", "-A"], cwd=work, check=True, timeout=60)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=work, check=True, timeout=60)

    outside = tmp_path / "outside.txt"
    outside.write_text("SECRET\n", encoding="utf-8")

    run_audit(work, SENSORS, DETECTORS, persist=True, compact=True)
    findings = Ledger(work / ".sopcontrol/evidence/ledger.jsonl").load_findings()
    fn = next(f for f in findings if f.pattern_id == "schema_field_unread")
    task = open_repair(work, fn.finding_id, ["src"], SENSORS, DETECTORS)
    store = TaskStore(work)
    d = evaluate_transition(task, "accept", known_rule_ids={fn.rule_id})
    store.apply(task, d, "accept")
    task = store.load(task.task_id)

    def runner(wt: Path, prompt: str):
        (wt / "src" / "evil.py").symlink_to(outside)

    result = apply_repair(work, task.task_id, runner=runner)
    assert "src/evil.py" in result["rejected_out_of_contract"]
    assert "src/evil.py" not in result["copied"]
    assert not (work / "src" / "evil.py").exists()
    assert outside.read_text() == "SECRET\n"


def test_apply_repair_rejects_source_replaced_by_symlink_after_check(
    tmp_path, monkeypatch
):
    """源文件通过 resolves_inside 后被换成仓外 symlink，也不能读取仓外内容。"""
    work, finding = _repair_work(tmp_path)
    task = open_repair(work, finding.finding_id, ["src"], SENSORS, DETECTORS)

    outside = tmp_path / "outside.txt"
    outside.write_text("EXTERNAL SECRET\n", encoding="utf-8")

    def runner(wt: Path, prompt: str):
        (wt / "src" / "race.py").write_text("safe content\n", encoding="utf-8")

    import sopcontrol.repair as repair_module

    entered_copy = threading.Event()
    release_copy = threading.Event()
    original_copy = repair_module.copy_paths_to_main
    result: dict = {}
    errors: list[BaseException] = []

    def controlled_copy(source, destination, paths):
        entered_copy.set()
        assert release_copy.wait(timeout=5)
        return original_copy(source, destination, paths)

    monkeypatch.setattr(repair_module, "copy_paths_to_main", controlled_copy)

    def apply_in_thread():
        try:
            result.update(apply_repair(work, task.task_id, runner=runner))
        except BaseException as exc:
            errors.append(exc)

    apply_thread = threading.Thread(target=apply_in_thread)
    apply_thread.start()
    assert entered_copy.wait(timeout=5)

    raced_source = worktree_path(work, task.task_id) / "src" / "race.py"
    raced_source.unlink()
    raced_source.symlink_to(outside)
    release_copy.set()
    apply_thread.join(timeout=5)

    assert not apply_thread.is_alive()
    assert errors == []
    assert "src/race.py" in result["rejected_out_of_contract"]
    assert "src/race.py" not in result["copied"]
    assert not (work / "src" / "race.py").exists()
    assert outside.read_text(encoding="utf-8") == "EXTERNAL SECRET\n"


def _confirm_narrow(work: Path, rule_id: str, scope_paths: list[str]) -> None:
    registry = Registry(work / ".sopcontrol" / "rules" / "registry.yaml")
    params = {
        "action": "narrow",
        "reason": "repair apply scope test",
        "actor": "test-human",
        "scope_paths": scope_paths,
    }
    preview = registry.lifecycle_preview(rule_id, **params)
    registry.confirm_lifecycle(rule_id, preview_id=preview["preview_id"], **params)


def _repair_work(tmp_path):
    import subprocess

    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/shop-checkout", work)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True, timeout=60)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=work, check=True, timeout=60)
    subprocess.run(["git", "config", "user.name", "t"], cwd=work, check=True, timeout=60)
    subprocess.run(["git", "add", "-A"], cwd=work, check=True, timeout=60)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=work, check=True, timeout=60)
    run_audit(work, SENSORS, DETECTORS, persist=True, compact=True)
    from sopcontrol.ledger import Ledger

    findings = Ledger(work / ".sopcontrol/evidence/ledger.jsonl").load_findings()
    finding = next(f for f in findings if f.pattern_id == "schema_field_unread")
    return work, finding


def test_apply_repair_rechecks_scope_before_runner(tmp_path):
    work, finding = _repair_work(tmp_path)
    task = open_repair(work, finding.finding_id, ["docs"], SENSORS, DETECTORS)
    _confirm_narrow(work, finding.rule_id, ["src"])
    called = False

    def runner(wt: Path, prompt: str):
        nonlocal called
        called = True

    with pytest.raises(RepairError, match="docs.*scope"):
        apply_repair(work, task.task_id, runner=runner)
    assert called is False


def test_apply_repair_rechecks_scope_before_copy(tmp_path):
    work, finding = _repair_work(tmp_path)
    task = open_repair(work, finding.finding_id, ["src"], SENSORS, DETECTORS)

    def runner(wt: Path, prompt: str):
        (wt / "src" / "reporting.py").write_text(
            (wt / "src" / "reporting.py").read_text() + "\nx = schema_extra_field\n",
            encoding="utf-8",
        )
        _confirm_narrow(work, finding.rule_id, ["docs"])

    with pytest.raises(RepairError, match="src.*scope"):
        apply_repair(work, task.task_id, runner=runner)
    assert "x = schema_extra_field" not in (work / "src" / "reporting.py").read_text()


def test_apply_repair_holds_registry_lock_across_check_and_copy(
    tmp_path, monkeypatch
):
    work, finding = _repair_work(tmp_path)
    task = open_repair(work, finding.finding_id, ["src"], SENSORS, DETECTORS)

    def runner(wt: Path, prompt: str):
        (wt / "src" / "reporting.py").write_text(
            (wt / "src" / "reporting.py").read_text()
            + "\nx = schema_extra_field\n",
            encoding="utf-8",
        )

    import sopcontrol.repair as repair_module

    entered_copy = threading.Event()
    release_copy = threading.Event()
    lifecycle_done = threading.Event()
    original_copy = repair_module.copy_paths_to_main
    result: dict = {}
    errors: list[BaseException] = []

    def controlled_copy(source, destination, paths):
        entered_copy.set()
        assert release_copy.wait(timeout=5)
        return original_copy(source, destination, paths)

    monkeypatch.setattr(repair_module, "copy_paths_to_main", controlled_copy)

    def apply_in_thread():
        try:
            result.update(apply_repair(work, task.task_id, runner=runner))
        except BaseException as exc:
            errors.append(exc)

    def narrow_in_thread():
        try:
            _confirm_narrow(work, finding.rule_id, ["docs"])
        except BaseException as exc:
            errors.append(exc)
        finally:
            lifecycle_done.set()

    apply_thread = threading.Thread(target=apply_in_thread)
    apply_thread.start()
    assert entered_copy.wait(timeout=5)

    lifecycle_thread = threading.Thread(target=narrow_in_thread)
    lifecycle_thread.start()
    assert lifecycle_done.wait(timeout=0.2) is False

    release_copy.set()
    apply_thread.join(timeout=5)
    lifecycle_thread.join(timeout=5)

    assert not apply_thread.is_alive()
    assert not lifecycle_thread.is_alive()
    assert errors == []
    assert "src/reporting.py" in result["copied"]
    assert lifecycle_done.is_set()
    assert Registry(work / ".sopcontrol/rules/registry.yaml").get(
        finding.rule_id
    ).scope_paths == ["docs"]


def test_apply_repair_honors_file_write_granularity(tmp_path):
    work, finding = _repair_work(tmp_path)
    task = open_repair(work, finding.finding_id, ["src"], SENSORS, DETECTORS)
    store = TaskStore(work)
    task.contract.write_granularity = "file"
    task.revision += 1
    store.save(task)

    def runner(wt: Path, prompt: str):
        (wt / "src" / "reporting.py").write_text(
            (wt / "src" / "reporting.py").read_text() + "\nx = schema_extra_field\n",
            encoding="utf-8",
        )

    result = apply_repair(work, task.task_id, runner=runner)
    assert "src/reporting.py" in result["rejected_out_of_contract"]
    assert "src/reporting.py" not in result["copied"]
    assert "x = schema_extra_field" not in (work / "src" / "reporting.py").read_text()


def test_worktree_path_rejects_non_atomic_task_ids(tmp_path):
    for task_id in (
        "../evidence",
        "../../.sopcontrol/evidence",
        "TASK-1/../../evidence",
        r"..\\evidence",
        "/tmp/escape",
        "",
        ".",
        "..",
    ):
        try:
            worktree_path(tmp_path, task_id)
        except WorktreeError:
            pass
        else:
            raise AssertionError(f"非单一路径分量 task_id 被接受: {task_id!r}")

    expected = tmp_path / ".sopcontrol" / "worktrees" / "TASK-0001"
    assert worktree_path(tmp_path, "TASK-0001") == expected

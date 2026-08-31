"""CLI 层任务流回归：防止参数接线类 bug（曾因 args.changed 误引用翻车，实测捕获）。"""
import shutil
import threading
from datetime import datetime, timedelta, timezone

from sopcontrol.cli import main
from sopcontrol.registry import Registry
from sopcontrol.task import TaskStore


def _work(tmp_path):
    work = tmp_path / "proj"
    work.mkdir()
    shutil.copytree("corpus/fixtures/jobflow-preview", work, dirs_exist_ok=True)
    return work


def _change_rule_lifecycle(work, action, **kwargs):
    registry = Registry(work / ".sopcontrol" / "rules" / "registry.yaml")
    params = {
        "action": action,
        "reason": "task scope test",
        "actor": "test-human",
        **kwargs,
    }
    preview = registry.lifecycle_preview("PUSH-001", **params)
    registry.confirm_lifecycle(
        "PUSH-001", preview_id=preview["preview_id"], **params
    )


def _open_task(work, *allows):
    command = [
        "task", "open", str(work),
        "--objective", "接线 PUSH-001",
        "--require-rule", "PUSH-001",
        "--require-field", "status",
    ]
    for path in allows:
        command.extend(["--allow", path])
    return main(command)


def test_task_lifecycle_via_cli(tmp_path, capsys):
    work = tmp_path / "proj"
    work.mkdir()
    shutil.copytree("corpus/fixtures/jobflow-preview", work, dirs_exist_ok=True)

    assert main(["capability-eval", "--model", "lifecycle-test", "--fixture", "strong", str(work)]) == 0
    assert main(["task", "open", str(work),
                 "--model", "lifecycle-test",
                 "--objective", "接线 PUSH-001",
                 "--allow", "src/push_job.py", "--allow", "tests/test_push.py",
                 "--require-rule", "PUSH-001", "--require-field", "status"]) == 0
    assert main(["task", "accept", "TASK-0001", str(work)]) == 0
    assert main(["task", "submit", "TASK-0001", str(work),
                 "--changed", "src/push_job.py", "--field", "status=initial"]) == 0
    assert main(["task", "verify", "TASK-0001", str(work)]) == 0  # PUSH-001 gap → repair_required

    # 真实接线（注意：不在注释里写标记词——R1 反向家族教训）
    (work / "src" / "push_job.py").write_text(
        "def require_preview(rows):\n    return rows\n\n\ndef push_job(sheet, row):\n    require_preview([row])\n    sheet.append(row)\n",
        encoding="utf-8",
    )
    (work / "tests" / "test_push.py").write_text(
        "from push_job import require_preview\n\ndef test_preview():\n    assert require_preview([]) == []\n",
        encoding="utf-8",
    )
    assert main(["task", "submit", "TASK-0001", str(work),
                 "--changed", "src/push_job.py", "--changed", "tests/test_push.py",
                 "--field", "status=fixed"]) == 0
    assert main(["task", "verify", "TASK-0001", str(work)]) == 0
    assert main(["task", "deliver", "TASK-0001", str(work)]) == 0

    out = capsys.readouterr().out
    assert "delivered" in out
    show = main(["task", "show", "TASK-0001", str(work)])
    assert show == 0


def test_task_open_rejects_writes_outside_effective_rule_scope(tmp_path, capsys):
    work = _work(tmp_path)
    _change_rule_lifecycle(work, "narrow", scope_paths=["src"])

    assert _open_task(work, "src/push_job.py", "docs/tracker-sop.md") == 2
    assert "docs/tracker-sop.md" in capsys.readouterr().err
    assert TaskStore(work).list_all() == []


def test_task_open_rejects_suspended_required_rule(tmp_path, capsys):
    work = _work(tmp_path)
    _change_rule_lifecycle(
        work,
        "suspend",
        until=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    assert _open_task(work, "src/push_job.py") == 2
    assert "当前有效规则" in capsys.readouterr().err
    assert TaskStore(work).list_all() == []


def test_task_accept_rechecks_current_effective_rule_scope(tmp_path, capsys):
    work = _work(tmp_path)
    assert _open_task(work, "docs/tracker-sop.md") == 0
    _change_rule_lifecycle(work, "narrow", scope_paths=["src"])
    capsys.readouterr()

    assert main(["task", "accept", "TASK-0001", str(work)]) == 0
    task = TaskStore(work).load("TASK-0001")
    assert task.status.value == "contract_proposed"
    output = capsys.readouterr().out
    assert "docs/tracker-sop.md" in output and "scope" in output


def test_task_accept_rechecks_required_rule_is_effective(tmp_path, capsys):
    work = _work(tmp_path)
    assert _open_task(work, "src/push_job.py") == 0
    _change_rule_lifecycle(
        work,
        "suspend",
        until=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    capsys.readouterr()

    assert main(["task", "accept", "TASK-0001", str(work)]) == 0
    task = TaskStore(work).load("TASK-0001")
    assert task.status.value == "contract_proposed"
    assert "PUSH-001" in capsys.readouterr().out


def test_task_submit_rechecks_current_effective_rule_scope(tmp_path, capsys):
    work = _work(tmp_path)
    assert _open_task(work, "src/push_job.py") == 0
    assert main(["task", "accept", "TASK-0001", str(work)]) == 0
    _change_rule_lifecycle(work, "narrow", scope_paths=["docs"])
    capsys.readouterr()

    assert main([
        "task", "submit", "TASK-0001", str(work),
        "--changed", "src/push_job.py", "--field", "status=done",
    ]) == 0
    task = TaskStore(work).load("TASK-0001")
    assert task.status.value == "executing"
    output = capsys.readouterr().out
    assert "src/push_job.py" in output and "scope" in output


def test_task_verify_rechecks_required_rule_is_effective(tmp_path, capsys):
    work = _work(tmp_path)
    assert _open_task(work, "src/push_job.py") == 0
    assert main(["task", "accept", "TASK-0001", str(work)]) == 0
    assert main([
        "task", "submit", "TASK-0001", str(work),
        "--changed", "src/push_job.py", "--field", "status=done",
    ]) == 0
    _change_rule_lifecycle(
        work,
        "suspend",
        until=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    capsys.readouterr()

    assert main(["task", "verify", "TASK-0001", str(work)]) == 0
    task = TaskStore(work).load("TASK-0001")
    assert task.status.value == "blocked"
    output = capsys.readouterr().out
    assert "PUSH-001" in output and "effective" in output


def test_task_accept_holds_registry_lock_through_task_save(tmp_path, monkeypatch):
    work = _work(tmp_path)
    assert _open_task(work, "src/push_job.py") == 0

    entered_save = threading.Event()
    release_save = threading.Event()
    lifecycle_done = threading.Event()
    errors: list[BaseException] = []
    original_save = TaskStore.save

    def controlled_save(self, task, expected_revision=None):
        if threading.current_thread().name == "task-accept":
            entered_save.set()
            assert release_save.wait(timeout=5)
        return original_save(self, task, expected_revision=expected_revision)

    monkeypatch.setattr(TaskStore, "save", controlled_save)

    def accept_task():
        try:
            main(["task", "accept", "TASK-0001", str(work)])
        except BaseException as exc:
            errors.append(exc)

    def narrow_rule():
        try:
            _change_rule_lifecycle(work, "narrow", scope_paths=["docs"])
        except BaseException as exc:
            errors.append(exc)
        finally:
            lifecycle_done.set()

    accept_thread = threading.Thread(target=accept_task, name="task-accept")
    accept_thread.start()
    assert entered_save.wait(timeout=5)

    lifecycle_thread = threading.Thread(target=narrow_rule, name="rule-narrow")
    lifecycle_thread.start()
    assert lifecycle_done.wait(timeout=0.2) is False

    release_save.set()
    accept_thread.join(timeout=5)
    lifecycle_thread.join(timeout=5)

    assert not accept_thread.is_alive() and not lifecycle_thread.is_alive()
    assert errors == []
    assert TaskStore(work).load("TASK-0001").status.value == "executing"
    assert Registry(work / ".sopcontrol/rules/registry.yaml").get(
        "PUSH-001"
    ).scope_paths == ["docs"]

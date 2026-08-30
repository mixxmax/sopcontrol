"""CLI 层任务流回归：防止参数接线类 bug（曾因 args.changed 误引用翻车，实测捕获）。"""
import shutil

from sopcontrol.cli import main


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

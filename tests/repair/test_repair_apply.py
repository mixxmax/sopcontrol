"""自动修复者 + worktree：注入 runner，不烧 token。"""
import shutil
from pathlib import Path

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit
from sopcontrol.cli import main
from sopcontrol.repair import apply_repair, open_repair
from sopcontrol.task import TaskStatus, TaskStore
from sopcontrol.worktree import WorktreeError, worktree_path
from sopcontrol.worktree import WorktreeError, worktree_path


def test_apply_repair_merges_allowed_paths_only(tmp_path):
    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/shop-checkout", work)
    # need git for worktree
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=work, check=True)
    subprocess.run(["git", "add", "-A"], cwd=work, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=work, check=True)

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
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=work, check=True)
    subprocess.run(["git", "add", "-A"], cwd=work, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=work, check=True)

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

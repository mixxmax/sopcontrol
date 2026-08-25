"""自动修复者 + worktree：注入 runner，不烧 token。"""
import shutil
from pathlib import Path

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit
from sopcontrol.cli import main
from sopcontrol.repair import apply_repair, open_repair
from sopcontrol.task import TaskStatus, TaskStore


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

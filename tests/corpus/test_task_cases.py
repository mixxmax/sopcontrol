"""任务语料执行器：把 task_cases.yaml 的脚本化步骤跑在真实任务 API 上（拷贝夹具到临时目录）。"""
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit, run_task_verify
from sopcontrol.registry import Registry
from sopcontrol.task import Contract, TaskRecord, TaskStore, evaluate_transition

ROOT = Path(__file__).resolve().parents[2]
CASES = yaml.safe_load((ROOT / "corpus" / "task_cases.yaml").read_text(encoding="utf-8"))["cases"]


def test_task_corpus_nonempty():
    assert CASES, "任务语料为空——fail-on-empty 守卫"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
def test_task_case(case, tmp_path):
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / case["fixture"], work)
    store = TaskStore(work)
    task = None

    for step in case["steps"]:
        do = step["do"]

        if do == "open":
            kwargs = dict(
                objective=step["objective"],
                allowed_writes=list(step.get("allow", [])),
                required_rules=list(step.get("require_rules", [])),
                required_fields=list(step.get("require_fields", [])),
                strict_schema=bool(step.get("strict_schema", False)),
            )
            if "max_repairs" in step:
                kwargs["max_repairs"] = step["max_repairs"]
            task = TaskRecord(task_id=store.next_task_id(), contract=Contract(**kwargs))
            store.save(task)

        elif do == "write_file":
            target = work / step["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(step["content"], encoding="utf-8")

        elif do == "audit":
            run_audit(work, SENSORS, DETECTORS, persist=True)

        elif do == "tamper_ledger":
            ledger = work / ".sopcontrol" / "evidence" / "ledger.jsonl"
            ledger.parent.mkdir(parents=True, exist_ok=True)
            with ledger.open("a", encoding="utf-8") as fh:
                fh.write(
                    '{"evidence_id": "ev-fake", "kind": "code_scan.identifiers", "subject": "src/x.py",'
                    ' "observed": ["x"], "observer": "code_scan", "input_hash": "deadbeef"}\n'
                )

        elif do == "manifest":
            (work / ".sopcontrol" / "manifest.yaml").write_text(
                yaml.safe_dump({"controller_paths": step["controller_paths"]}, allow_unicode=True),
                encoding="utf-8",
            )

        elif do == "shell":
            subprocess.run(step["cmd"], shell=True, cwd=str(work), check=True)

        else:  # accept / submit / verify / deliver
            if do == "verify":
                decision = run_task_verify(work, SENSORS, DETECTORS, task)
            else:
                known = {r.rule_id for r in Registry(work / ".sopcontrol" / "rules" / "registry.yaml").load()}
                decision = evaluate_transition(
                    task, do,
                    changed_paths=step.get("changed"),
                    provided_fields=step.get("fields"),
                    known_rule_ids=known,
                )
            task = store.apply(task, decision, do, changed_paths=step.get("changed"))

            if "expect" in step:
                exp = step["expect"]
                assert decision.allowed == exp["allowed"], (
                    f"{case['case_id']}.{do}: allowed={decision.allowed} 期望 {exp['allowed']}；{decision.reason}"
                )
                to = decision.to_status.value if decision.to_status else None
                assert to == exp["to"], (
                    f"{case['case_id']}.{do}: to={to} 期望 {exp['to']}；{decision.reason}"
                )

    assert task is not None and task.status.value == case["final_status"], (
        f"{case['case_id']} 终态 {task.status.value if task else None}，期望 {case['final_status']}"
    )

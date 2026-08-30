"""B4 切片：接管包——最小信息、合法动作、不重解释契约。"""
import shutil

from sopcontrol.cli import main
from sopcontrol.task import LEGAL_ACTIONS, TaskStatus, takeover_pack


def test_takeover_pack_shape():
    from sopcontrol.task import Contract, TaskRecord

    task = TaskRecord(
        task_id="TASK-0007",
        contract=Contract(
            objective="接线规则 X", allowed_writes=["src"],
            required_rules=["X-001"], max_repairs=2,
        ),
        status=TaskStatus.repair_required,
        repair_count=1,
        changed_paths=["src/x.py"],
    )
    pack = takeover_pack(task, {"X-001": "gap"}, ["documented_rule_no_consumer(gap)"])
    assert pack["status"] == "repair_required"
    assert pack["repair_budget"] == "1/2"
    assert pack["rule_verdicts"] == {"X-001": "gap"}
    assert pack["next_legal_actions"] == LEGAL_ACTIONS[TaskStatus.repair_required]
    assert "不得重新解释" in pack["note"]


def test_takeover_via_cli_is_readonly(tmp_path, capsys):
    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/ci-deploy", work)
    # gate 测试可能在真实夹具里留下 gitignored 账本；只读断言要求从零开始
    ledger = work / ".sopcontrol" / "evidence" / "ledger.jsonl"
    ledger.unlink(missing_ok=True)
    assert main(["capability-eval", "--model", "takeover-test", "--fixture", "strong", str(work)]) == 0
    assert main(["task", "open", str(work), "--model", "takeover-test",
                 "--objective", "接线 DEPLOY-001", "--allow", "scripts/deploy.py",
                 "--require-rule", "DEPLOY-001"]) == 0
    assert main(["task", "accept", "TASK-0001", str(work)]) == 0
    assert main(["task", "takeover", "TASK-0001", str(work)]) == 0
    out = capsys.readouterr().out
    assert "executing" in out and "DEPLOY-001" in out
    assert "submit" in out  # 合法下一步
    # 只读：接管不应产生账本写入
    assert not ledger.exists()

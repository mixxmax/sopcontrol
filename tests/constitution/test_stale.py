"""场景14：输入变化使旧 evidence stale——不得继续支撑通过判定。"""
import shutil

from sopcontrol.cli import main
from sopcontrol.stale import is_input_stale, partition_evidence
from sopcontrol.ledger import Ledger


def test_scenario14_input_change_stales_ledger_evidence(tmp_path, capsys):
    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/shop-checkout", work)
    # 夹具可能自带历史账本（旧 hash）——场景14测的是本轮写入后输入再变
    ledger_path = work / ".sopcontrol" / "evidence" / "ledger.jsonl"
    ledger_path.unlink(missing_ok=True)

    assert main(["audit", str(work)]) == 0
    ledger = Ledger(ledger_path)
    before = ledger.load_evidence(current_only=False)
    assert before
    fresh, stale = partition_evidence(work, before)
    assert fresh and not stale

    # 改生产消费者文件 → 旧证据 input_hash 失效
    target = work / "src" / "checkout.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# touch\n", encoding="utf-8")

    fresh2, stale2 = partition_evidence(work, before)
    assert any(is_input_stale(work, e) for e in before if e.subject == "src/checkout.py")
    assert any(e.subject == "src/checkout.py" for e in stale2)

    assert main(["doctor", str(work)]) == 0
    out = capsys.readouterr().out
    assert "stale" in out.lower() or "stale" in out

    # explain 不得用 stale 证据假装仍 wired（应提示 stale 并基于新鲜子集判定）
    assert main(["explain", "REFUND-001", str(work)]) == 0
    out = capsys.readouterr().out
    assert "stale" in out.lower() or "场景14" in out


def test_trace_evidence_not_falsely_staled(tmp_path):
    """运行时 trace 行不得被文件哈希兜底分支误杀（首次 enforced 走查抓到的真 bug）。

    trace 的 input_hash 是观测汇总的哈希，不是 trace.jsonl 的文件哈希——
    掉进兜底分支的后果是每条 trace 行一落盘即 stale，explain/doctor 的账本
    视图永远看不见条件6，enforced 在任何记录里都不可见。修法与成熟度同构：
    重算当前汇总，不一致才 stale。
    """
    from sopcontrol.trace import append_event, trace_evidence

    work = tmp_path / "work"
    work.mkdir()
    (work / ".sopcontrol" / "evidence").mkdir(parents=True)

    append_event(work, tool="Write", decision="allow", rule_ids=["GUARD-CONTROLLER-WRITE"])
    row = trace_evidence(work)
    assert row is not None
    assert not is_input_stale(work, row), "与当前汇总一致的 trace 行被误判 stale"

    # 新事件到来 → 旧汇总退场；重新观测的新汇总仍新鲜
    append_event(work, tool="Write", decision="deny", rule_ids=["GUARD-CONTROLLER-WRITE"])
    assert is_input_stale(work, row), "trace.jsonl 变化后旧 trace 行必须退场"
    row2 = trace_evidence(work)
    assert row2 is not None and row2.input_hash != row.input_hash
    assert not is_input_stale(work, row2)

    # 事件清空 = 结论消失 = stale（fail-closed）
    (work / ".sopcontrol" / "evidence" / "trace.jsonl").unlink()
    assert is_input_stale(work, row2)

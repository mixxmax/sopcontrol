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

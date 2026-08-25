"""账本 compact：整轮快照替换，清除 stale 噪音。"""
from pathlib import Path

from plugins import DETECTORS, SENSORS
from sopcontrol.audit import run_audit
from sopcontrol.cli import main
from sopcontrol.ledger import Ledger
from sopcontrol.stale import partition_evidence


def test_compact_replaces_stale_noise(tmp_path):
    import shutil

    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/shop-checkout", work)
    ledger_path = work / ".sopcontrol" / "evidence" / "ledger.jsonl"
    ledger_path.unlink(missing_ok=True)

    run_audit(work, SENSORS, DETECTORS, persist=True)
    # 改文件制造 stale
    src = work / "src" / "checkout.py"
    src.write_text(src.read_text(encoding="utf-8") + "\n# touch\n", encoding="utf-8")
    ledger = Ledger(ledger_path)
    _, stale_before = partition_evidence(work, ledger.load_evidence(current_only=False))
    assert stale_before

    run_audit(work, SENSORS, DETECTORS, persist=True, compact=True)
    fresh, stale_after = partition_evidence(work, ledger.load_evidence(current_only=False))
    assert fresh and not stale_after


def test_cli_audit_compact(tmp_path):
    import shutil

    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/ci-deploy", work)
    (work / ".sopcontrol" / "evidence" / "ledger.jsonl").unlink(missing_ok=True)
    assert main(["audit", str(work), "--compact"]) == 0
    text = (work / ".sopcontrol" / "evidence" / "ledger.jsonl").read_text(encoding="utf-8")
    assert "evidence_id" in text

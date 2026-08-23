"""宪法测试：账本追加式、内容寻址幂等、可校验篡改、过期即失效。"""
import json

from sopcontrol.ledger import Ledger
from sopcontrol.model import Evidence, Finding
from datetime import datetime, timedelta, timezone


def make_evidence(subject="src/a.py", **overrides) -> Evidence:
    base = dict(
        kind="code_scan.identifiers",
        subject=subject,
        observed=["marker_a"],
        observer="code_scan",
        input_hash="h1",
    )
    base.update(overrides)
    return Evidence(**base)


def test_append_is_idempotent(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ev = make_evidence()
    ledger.append_evidence(ev)
    ledger.append_evidence(make_evidence())  # 同内容重放
    lines = (tmp_path / "ledger.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1


def test_prior_records_unchanged_after_append(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append_evidence(make_evidence(subject="src/a.py"))
    before = (tmp_path / "ledger.jsonl").read_text()
    ledger.append_evidence(make_evidence(subject="src/b.py"))
    after = (tmp_path / "ledger.jsonl").read_text()
    assert after.startswith(before)
    assert len(after.splitlines()) == 2


def test_tampering_is_detected(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append_evidence(make_evidence())
    ledger.append_finding(
        Finding(pattern_id="p", rule_id="R-1", summary="s", severity="gap", detector="d")
    )
    assert ledger.verify() is True

    path = tmp_path / "ledger.jsonl"
    lines = path.read_text().splitlines()
    record = json.loads(lines[0])
    record["observed"] = ["tampered"]
    lines[0] = json.dumps(record, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n")
    assert ledger.verify() is False


def test_expired_evidence_excluded(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    expired = make_evidence(
        subject="src/old.py",
        valid_until=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    fresh = make_evidence(subject="src/new.py")
    ledger.append_evidence(expired)
    ledger.append_evidence(fresh)
    current = ledger.load_evidence(current_only=True)
    assert [e.subject for e in current] == ["src/new.py"]
    assert len(ledger.load_evidence(current_only=False)) == 2

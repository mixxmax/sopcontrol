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


def test_concurrent_append_same_evidence_is_idempotent(tmp_path):
    """两线程追加同一 Evidence：最终只有一条。"""
    import threading

    ledger = Ledger(tmp_path / "ledger.jsonl")
    ev = make_evidence(subject="src/same.py")
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(40):
                ledger.append_evidence(ev)
        except BaseException as exc:  # noqa: BLE001 — 收集线程异常
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    lines = [ln for ln in ledger.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    assert ledger.verify() is True


def test_concurrent_append_distinct_evidence_keeps_all(tmp_path):
    """两线程追加不同 Evidence：两条都保留。"""
    import threading

    ledger = Ledger(tmp_path / "ledger.jsonl")
    errors: list[BaseException] = []

    def worker(subject: str) -> None:
        try:
            ledger.append_evidence(make_evidence(subject=subject))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(f"src/w{i}.py",))
        for i in range(20)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    lines = [ln for ln in ledger.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 20
    assert ledger.verify() is True


def test_append_and_compact_concurrent_remain_valid(tmp_path):
    """append 与 compact 并发：最终 JSONL 完整可解析且 verify 通过。"""
    import threading
    import time

    ledger = Ledger(tmp_path / "ledger.jsonl")
    for i in range(5):
        ledger.append_evidence(make_evidence(subject=f"src/seed{i}.py"))
    errors: list[BaseException] = []
    stop = threading.Event()

    def appender() -> None:
        try:
            n = 0
            while not stop.is_set() and n < 60:
                ledger.append_evidence(make_evidence(subject=f"src/app{n}.py"))
                n += 1
                time.sleep(0.001)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def compactor() -> None:
        try:
            for round_i in range(20):
                evs = [
                    make_evidence(subject=f"src/snap{round_i}-{j}.py")
                    for j in range(3)
                ]
                ledger.replace_snapshot(evs, [])
                time.sleep(0.002)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t_append = threading.Thread(target=appender)
    t_compact = threading.Thread(target=compactor)
    t_append.start()
    t_compact.start()
    t_compact.join()
    stop.set()
    t_append.join()
    assert not errors
    text = ledger.path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip():
            json.loads(line)
    assert ledger.verify() is True


def test_replace_snapshot_keeps_old_file_on_write_failure(tmp_path, monkeypatch):
    """写入异常时旧账本仍完整（原子替换失败不丢原文件）。"""
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append_evidence(make_evidence(subject="src/keep.py"))
    before = ledger.path.read_text(encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("simulated write failure")

    monkeypatch.setattr("sopcontrol.ledger.os.replace", boom)
    try:
        ledger.replace_snapshot([make_evidence(subject="src/new.py")], [])
        raised = False
    except OSError:
        raised = True
    assert raised
    assert ledger.path.read_text(encoding="utf-8") == before
    assert ledger.verify() is True


def test_corrupt_line_fails_verify_closed(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append_evidence(make_evidence())
    with ledger.path.open("a", encoding="utf-8") as fh:
        fh.write("{not-json\n")
    assert ledger.verify() is False

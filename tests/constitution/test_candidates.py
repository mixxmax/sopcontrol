"""第四批：重复行为聚合为可审查 Candidate，但永不自动获得授权。"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from sopcontrol.candidate import (
    CandidateSource,
    CandidateStore,
    correction_observation,
    refresh_candidates,
)
from sopcontrol.capability import control_knobs
from sopcontrol.capability_events import CapabilityEvent, append_capability_event
from sopcontrol.cli import main
from sopcontrol.harness import check_tool_call
from sopcontrol.ledger import Ledger
from sopcontrol.model import Finding


def test_legacy_candidate_schema_loads_without_losing_identity(tmp_path):
    path = tmp_path / ".sopcontrol" / "rules" / "candidates.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump([
            {
                "candidate_id": "CAND-007",
                "statement": "以后必须先预览",
                "suggested_modality": "MUST",
                "source": {"type": "document", "ref": "docs/sop.md"},
                "status": "observed",
                "note": "legacy",
            }
        ], allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    candidate = CandidateStore(tmp_path).load()[0]

    assert candidate.candidate_id == "CAND-007"
    assert candidate.statement == "以后必须先预览"
    assert candidate.frequency == 1
    assert candidate.sources[0].source_type == "document"
    assert candidate.sources[0].ref == "docs/sop.md"
    assert candidate.note == "legacy"


def test_fingerprint_and_id_are_stable_and_occurrences_deduplicate(tmp_path):
    store = CandidateStore(tmp_path)
    source = CandidateSource(
        source_type="correction",
        ref="checkout",
        occurrence_id="correction-1",
    )
    first, created = store.upsert(
        kind="correction",
        statement="结账流程应从 direct 改为 gateway",
        scope_guess="checkout",
        suggested_action="register_rule",
        suggested_modality="MUST",
        source=source,
    )
    second, created_again = store.upsert(
        kind="correction",
        statement="  结账流程应从 direct 改为 gateway  ",
        scope_guess="checkout",
        suggested_action="register_rule",
        suggested_modality="MUST",
        source=source,
    )

    assert created is True
    assert created_again is False
    assert first.candidate_id == second.candidate_id
    assert first.fingerprint == second.fingerprint
    assert second.frequency == 1

    third, _ = store.upsert(
        kind="correction",
        statement="结账流程应从 direct 改为 gateway",
        scope_guess="checkout",
        suggested_action="register_rule",
        suggested_modality="MUST",
        source=source.model_copy(update={"occurrence_id": "correction-2"}),
    )
    assert third.frequency == 2


def test_guard_denials_need_three_distinct_occurrences(tmp_path):
    for index in range(2):
        append_capability_event(
            tmp_path,
            CapabilityEvent(
                kind="guard.decision",
                subject="Bash",
                outcome="deny",
                detail={"rule_ids": ["GUARD-CONTROLLER-BASH"], "attempt": index},
            ),
        )
    assert refresh_candidates(tmp_path)["materialized"] == 0
    assert CandidateStore(tmp_path).load() == []

    append_capability_event(
        tmp_path,
        CapabilityEvent(
            kind="guard.decision",
            subject="Bash",
            outcome="deny",
            detail={"rule_ids": ["GUARD-CONTROLLER-BASH"], "attempt": 2},
        ),
    )
    result = refresh_candidates(tmp_path)
    candidates = CandidateStore(tmp_path).load()

    assert result["materialized"] == 1
    assert len(candidates) == 1
    assert candidates[0].kind == "guard_pattern"
    assert candidates[0].frequency == 3
    assert "GUARD-CONTROLLER-BASH" in candidates[0].statement

    assert refresh_candidates(tmp_path)["materialized"] == 0
    assert CandidateStore(tmp_path).load()[0].frequency == 3


def test_findings_group_by_fingerprint_and_do_not_write_registry(tmp_path):
    registry = tmp_path / ".sopcontrol" / "rules" / "registry.yaml"
    registry.parent.mkdir(parents=True)
    registry.write_text("rules: []\n", encoding="utf-8")
    ledger = Ledger(tmp_path / ".sopcontrol" / "evidence" / "ledger.jsonl")
    for index in range(3):
        ledger.append_finding(Finding(
            pattern_id="write_only_state",
            rule_id="R-1",
            summary=f"第 {index} 次发现只写不读",
            detector="test",
        ))

    result = refresh_candidates(tmp_path)
    candidates = CandidateStore(tmp_path).load()

    assert result["materialized"] == 1
    assert candidates[0].kind == "finding_pattern"
    assert candidates[0].frequency == 3
    assert registry.read_text(encoding="utf-8") == "rules: []\n"


def test_structured_corrections_use_distinct_occurrences_and_threshold(tmp_path):
    for _ in range(3):
        correction_observation(
            tmp_path,
            object_name="checkout",
            actual="direct-write",
            expected="gateway",
            scope="payments",
        )

    assert refresh_candidates(tmp_path)["materialized"] == 1
    candidate = CandidateStore(tmp_path).load()[0]
    assert candidate.kind == "correction"
    assert candidate.frequency == 3
    assert "direct-write" in candidate.statement
    assert "gateway" in candidate.statement


def test_candidate_cli_list_show_and_triage_are_non_authoritative(tmp_path, capsys):
    correction_observation(
        tmp_path,
        object_name="checkout",
        actual="direct-write",
        expected="gateway",
        scope="payments",
    )
    correction_observation(
        tmp_path,
        object_name="checkout",
        actual="direct-write",
        expected="gateway",
        scope="payments",
    )
    correction_observation(
        tmp_path,
        object_name="checkout",
        actual="direct-write",
        expected="gateway",
        scope="payments",
    )

    assert main(["candidate", "refresh", str(tmp_path)]) == 0
    capsys.readouterr()
    candidate = CandidateStore(tmp_path).load()[0]
    assert main(["candidate", "list", str(tmp_path), "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["candidate_id"] == candidate.candidate_id
    assert main(["candidate", "show", candidate.candidate_id, str(tmp_path), "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["frequency"] == 3
    assert main([
        "candidate", "triage", candidate.candidate_id, str(tmp_path),
        "--status", "triaged",
    ]) == 0
    assert CandidateStore(tmp_path).get(candidate.candidate_id).status == "triaged"
    assert main(["candidate", "refresh", str(tmp_path)]) == 0
    assert CandidateStore(tmp_path).get(candidate.candidate_id).status == "triaged"

    assert not (tmp_path / ".sopcontrol" / "rules" / "registry.yaml").exists()
    assert control_knobs("unknown").write_granularity == "file"
    decision = check_tool_call({"tool_name": "Write", "tool_input": {"file_path": "src/x.py"}})
    assert decision.permissionDecision == "allow"


def test_batch_triage_is_atomic_and_saves_once(tmp_path, monkeypatch, capsys):
    store = CandidateStore(tmp_path)
    records = []
    for index in range(2):
        record, _ = store.upsert(
            kind="correction",
            statement=f"策略 {index} 必须经 gateway",
            scope_guess="payments",
            suggested_action="register_rule",
            suggested_modality="MUST",
            source=CandidateSource(
                source_type="correction",
                ref=f"checkout-{index}",
                occurrence_id=f"corr-{index}",
            ),
        )
        records.append(record)

    saves = 0
    original_save = CandidateStore.save

    def count_save(self, values):
        nonlocal saves
        saves += 1
        return original_save(self, values)

    monkeypatch.setattr(CandidateStore, "save", count_save)
    assert main([
        "candidate", "batch-triage", str(tmp_path),
        "--candidate-id", records[0].candidate_id,
        "--candidate-id", records[1].candidate_id,
        "--status", "rejected",
    ]) == 0
    assert saves == 1
    assert {record.status for record in CandidateStore(tmp_path).load()} == {"rejected"}
    assert "未写入 registry" in capsys.readouterr().out
    assert not (tmp_path / ".sopcontrol" / "rules" / "registry.yaml").exists()


def test_batch_triage_unknown_id_changes_nothing(tmp_path):
    store = CandidateStore(tmp_path)
    record, _ = store.upsert(
        kind="policy",
        statement="必须保留原子性",
        scope_guess="project",
        suggested_action="register_rule",
        suggested_modality="MUST",
        source=CandidateSource(
            source_type="document",
            ref="docs/sop.md",
            occurrence_id="doc-1",
        ),
    )
    before = store.path.read_bytes()

    assert main([
        "candidate", "batch-triage", str(tmp_path),
        "--candidate-id", record.candidate_id,
        "--candidate-id", "CAND-missing",
        "--status", "triaged",
    ]) == 2
    assert store.path.read_bytes() == before
    assert store.get(record.candidate_id).status == "observed"


def test_triage_rejects_non_lifecycle_statuses(tmp_path):
    store = CandidateStore(tmp_path)
    record, _ = store.upsert(
        kind="policy",
        statement="必须显式裁决",
        scope_guess="project",
        suggested_action="register_rule",
        suggested_modality="MUST",
        source=CandidateSource(
            source_type="document",
            ref="docs/sop.md",
            occurrence_id="doc-2",
        ),
    )
    for status in ("observed", "promoted", "accepted"):
        try:
            store.triage_many([record.candidate_id], status)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError(f"非法状态 {status} 被接受")
    assert store.get(record.candidate_id).status == "observed"


def test_candidate_code_is_not_imported_by_hot_authority_paths():
    for path in (
        "sopcontrol/capability.py",
        "sopcontrol/harness.py",
        "sopcontrol/task.py",
        "sopcontrol/cli_common.py",
    ):
        assert "candidate" not in Path(path).read_text(encoding="utf-8")

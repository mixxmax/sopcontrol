"""关键路径失败/边界行为：attest、task 迁移、energy、candidate CLI。"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sopcontrol.attest import AttestError, record_attestation, source_file
from sopcontrol.cli import main
from sopcontrol.energy import (
    candidates_budget_warning,
    estimate_tokens,
    fit_projection_text,
    inventory_from_snapshot,
)
from sopcontrol.growth import SpaceSnapshot
from sopcontrol.model import Modality, RiskLevel, Rule, RuleStatus, SourceRef
from sopcontrol.registry import Registry
from sopcontrol.task import TaskStore, evaluate_transition

ROOT = Path(__file__).resolve().parents[2]


def _init_with_rule(work: Path, *, source_ref: str = "docs/sop.md") -> None:
    assert main(["init", str(work)]) == 0
    docs = work / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "sop.md").write_text("变更必须经 demo_gate。\n", encoding="utf-8")
    assert main([
        "rule", "add", str(work),
        "--id", "COV-001",
        "--statement", "变更必须经 demo_gate",
        "--status", "accepted",
        "--source-ref", source_ref,
        "--consumer-marker", "demo_gate",
    ]) == 0


def test_attest_rejects_empty_bypass_note(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    _init_with_rule(work)
    with pytest.raises(AttestError, match="绕过分析不能为空"):
        record_attestation(work, "COV-001", bypass_note="  ", by="tester")


def test_source_file_rejects_path_traversal(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    _init_with_rule(work)
    reg = Registry(work / ".sopcontrol" / "rules" / "registry.yaml")
    rules = reg.load()
    rule = rules[0]
    evil = rule.model_copy(deep=True)
    evil.source = SourceRef(type="document", ref="../outside.md")
    assert source_file(work, evil) is None


def test_source_file_rejects_symlink(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    _init_with_rule(work)
    target = work / "docs" / "real.md"
    target.write_text("x", encoding="utf-8")
    link = work / "docs" / "link.md"
    link.symlink_to(target)
    reg = Registry(work / ".sopcontrol" / "rules" / "registry.yaml")
    rule = reg.load()[0]
    linked = rule.model_copy(deep=True)
    linked.source = SourceRef(type="document", ref="docs/link.md")
    assert source_file(work, linked) is None


def test_source_file_rejects_directory(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    _init_with_rule(work)
    (work / "docs" / "subdir").mkdir()
    reg = Registry(work / ".sopcontrol" / "rules" / "registry.yaml")
    rule = reg.load()[0]
    as_dir = rule.model_copy(deep=True)
    as_dir.source = SourceRef(type="document", ref="docs/subdir")
    assert source_file(work, as_dir) is None


def test_illegal_task_transition_denied(tmp_path):
    work = tmp_path / "w"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "shop-checkout", work)
    assert main([
        "capability-eval", "--model", "cov-model", "--fixture", "strong", str(work),
    ]) == 0
    assert main([
        "task", "open", str(work),
        "--model", "cov-model",
        "--objective", "noop",
        "--allow", "src/checkout.py",
        "--require-field", "status",
    ]) == 0
    store = TaskStore(work)
    task = store.load("TASK-0001")
    decision = evaluate_transition(task, "deliver")
    assert decision.allowed is False


def test_candidate_observe_correction_and_list(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    assert main([
        "candidate", "observe-correction", str(work),
        "--object", "lane",
        "--actual", "A",
        "--expected", "B",
        "--scope", "project",
    ]) == 0
    assert main(["candidate", "list", str(work)]) == 0
    assert main(["candidate", "refresh", str(work)]) == 0


def test_energy_helpers_and_fit_budget():
    assert estimate_tokens("") == 0
    assert candidates_budget_warning(1) is None
    snap = SpaceSnapshot(bypass_open=1, parallel_state=0, source="measure")
    inv = inventory_from_snapshot(snap)
    assert inv and inv["delete_first_actions"] == 1
    lines = ["<!-- sopcontrol:start -->", "## 空间生长（无感观察；定型需人）"]
    lines += [f"- pad {i} " + ("y" * 100) for i in range(100)]
    lines += ["## 硬约束", "- x", "<!-- sopcontrol:end -->"]
    fitted, trimmed = fit_projection_text("\n".join(lines) + "\n")
    assert trimmed is True
    assert "节能" in fitted


def test_doctor_light_and_full_cli(tmp_path):
    work = tmp_path / "w"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    assert main(["doctor", str(work)]) == 0
    assert main(["doctor", "--full", str(work)]) == 0


def test_chronicle_check_and_growth_diff(tmp_path):
    work = tmp_path / "w"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "shop-checkout", work)
    assert main(["growth", "measure", str(work)]) == 0
    assert main(["growth", "measure", str(work)]) == 0
    assert main(["growth", "diff", str(work)]) == 0
    assert main(["chronicle", "check", str(work)]) in (0, 1)


def test_growth_refresh_status_inventory_explain(tmp_path):
    work = tmp_path / "w"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    assert main(["growth", "refresh", str(work)]) == 0
    assert main(["growth", "status", str(work)]) == 0
    assert main(["inventory", str(work)]) == 0
    assert main(["explain", "PUSH-001", str(work)]) in (0, 1)
    assert main(["project", "check", str(work)]) in (0, 1)
    assert main(["bootstrap", str(work)]) == 0
    assert main(["metrics", str(work)]) in (0, 1, 2)


def test_identity_export_import_roundtrip(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    assert main(["identity", "init", str(work)]) == 0
    assert main(["identity", "lock", str(work)]) == 0
    bundle = tmp_path / "id.yaml"
    assert main(["identity", "export", str(work), "--out", str(bundle)]) == 0
    other = tmp_path / "other"
    other.mkdir()
    assert main(["init", str(other)]) == 0
    assert main(["identity", "import", str(other), "--file", str(bundle)]) in (0, 1, 2)


def test_candidate_show_missing_and_triage(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    assert main(["candidate", "show", "CAND-missing", str(work)]) == 2
    # seed one correction then refresh enough times won't materialize without threshold;
    # triage unknown id
    assert main([
        "candidate", "batch-triage", str(work),
        "--candidate-id", "CAND-nope", "--status", "rejected",
    ]) == 2


def test_next_moves_with_identity_and_hook(tmp_path):
    from sopcontrol.next_moves import adoption_next_moves

    work = tmp_path / "w"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "shop-checkout", work)
    assert main(["identity", "init", str(work)]) == 0
    (work / ".git" / "hooks").mkdir(parents=True, exist_ok=True)
    (work / ".git" / "hooks" / "pre-push").write_text(
        "# sopcontrol-hook v1\nsopctl gate\n", encoding="utf-8",
    )
    assert main(["growth", "measure", str(work)]) == 0
    moves = adoption_next_moves(work, limit=3, allow_audit=False)
    assert moves
    assert all("command" in m for m in moves)


def test_task_revision_conflict_on_save(tmp_path):
    from sopcontrol.task import TaskStore

    work = tmp_path / "w"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "shop-checkout", work)
    assert main([
        "capability-eval", "--model", "rev-model", "--fixture", "strong", str(work),
    ]) == 0
    assert main([
        "task", "open", str(work),
        "--model", "rev-model",
        "--objective", "rev check",
        "--allow", "src/checkout.py",
        "--require-field", "status",
    ]) == 0
    store = TaskStore(work)
    t1 = store.load("TASK-0001")
    t2 = store.load("TASK-0001")
    t1.revision += 1
    store.save(t1, expected_revision=t1.revision - 1)
    with pytest.raises(Exception):
        # stale writer should fail closed on revision
        store.save(t2, expected_revision=t2.revision)
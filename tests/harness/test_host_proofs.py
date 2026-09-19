"""P0-2/P0-3：宿主证明结构化校验与注册表损坏分级（正式 harness 路径）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sopcontrol.cli import main
from sopcontrol.harness import decide_harness_action
from sopcontrol.model import (
    ActivationSelector,
    Modality,
    Rule,
    RuleStatus,
    SourceRef,
)
from sopcontrol.registry import Registry


def _init_project(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    assert main(["init", str(path)]) == 0


def _add_host_rule(work: Path, rule_id: str = "AUDIT-H") -> None:
    reg = Registry(work / ".sopcontrol" / "rules" / "registry.yaml")
    reg.add(Rule(rule_id=rule_id, statement="审计仅核对指定项",
                 modality=Modality.MUST, status=RuleStatus.compiled,
                 rule_class="dynamic_sop", source=SourceRef(ref="s"),
                 activation=ActivationSelector(actions=["audit"]),
                 consumer_markers=["audit-checker"]))
    reg.transition(rule_id, RuleStatus.accepted)


def _payload(**kw):
    base = {"tool_name": "Bash", "tool_input": {"command": "audit --jd"},
            "action": "audit", "task_id": "T1", "run_id": "run-1"}
    base.update(kw)
    return base


def _proof(work: Path, rule_id: str = "AUDIT-H", **over):
    from sopcontrol.action_plane import build_envelope
    from sopcontrol.harness import _load_effective_harness_rules

    payload = _payload()
    env = build_envelope(payload, harness="t")
    _, digest, _ = _load_effective_harness_rules(work)
    proof = {"proof_id": "pf-1", "verdict": "pass",
             "task_id": "T1", "target": env.target,
             "input_digest": env.input_fingerprint, "run_id": "run-1",
             "rules_digest": digest,
             "expires_at": (datetime.now(timezone.utc)
                            + timedelta(minutes=5)).isoformat(),
             "producer": "audit-checker"}
    proof.update(over)
    return payload, proof


def test_valid_proof_passes_and_replay_rejected(tmp_path):
    _init_project(tmp_path)
    _add_host_rule(tmp_path)
    payload, proof = _proof(tmp_path)
    first = decide_harness_action(dict(payload, host_proofs={"AUDIT-H": proof}),
                                  root=tmp_path, harness="t")
    assert first.decision in ("allow", "observe")
    assert "AUDIT-H" in first.rule_ids
    # 同一证明第二次兑换失败（单次消费）
    second = decide_harness_action(dict(payload, host_proofs={"AUDIT-H": proof}),
                                   root=tmp_path, harness="t")
    assert second.decision == "ask"
    assert "重放" in second.reason or "消费" in second.reason


def test_fail_verdict_rejected(tmp_path):
    _init_project(tmp_path)
    _add_host_rule(tmp_path)
    payload, proof = _proof(tmp_path, verdict="fail")
    decision = decide_harness_action(dict(payload, host_proofs={"AUDIT-H": proof}),
                                     root=tmp_path, harness="t")
    assert decision.decision == "ask"
    assert "verdict" in decision.reason


def test_expired_and_scalar_proofs_rejected(tmp_path):
    _init_project(tmp_path)
    _add_host_rule(tmp_path)
    payload, proof = _proof(
        tmp_path,
        expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    assert decide_harness_action(
        dict(payload, host_proofs={"AUDIT-H": proof}),
        root=tmp_path, harness="t").decision == "ask"
    assert decide_harness_action(
        dict(payload, host_proofs={"AUDIT-H": "yes-trust-me"}),
        root=tmp_path, harness="t").decision == "ask"


def test_binding_mismatch_rejected(tmp_path):
    _init_project(tmp_path)
    _add_host_rule(tmp_path)
    payload, proof = _proof(tmp_path, run_id="run-OTHER")
    assert decide_harness_action(
        dict(payload, host_proofs={"AUDIT-H": proof}),
        root=tmp_path, harness="t").decision == "ask"
    payload2, proof2 = _proof(tmp_path, task_id="T-OTHER")
    payload2["task_id"] = "T1"
    assert decide_harness_action(
        dict(payload2, host_proofs={"AUDIT-H": proof2}),
        root=tmp_path, harness="t").decision == "ask"


def test_malformed_proofs_object_asks(tmp_path):
    _init_project(tmp_path)
    _add_host_rule(tmp_path)
    decision = decide_harness_action(
        dict(_payload(), host_proofs=["not-a-dict"]),
        root=tmp_path, harness="t")
    assert decision.decision == "ask"


def test_readonly_needs_no_proofs(tmp_path):
    _init_project(tmp_path)
    _add_host_rule(tmp_path)
    decision = decide_harness_action(
        {"tool_name": "Read", "tool_input": {"file_path": "README.md"}},
        root=tmp_path, harness="t")
    assert decision.decision == "observe"


def test_corrupt_registry_read_observe_write_ask(tmp_path):
    _init_project(tmp_path)
    (tmp_path / ".sopcontrol" / "rules" / "registry.yaml").write_text(
        "rules: [unclosed\n", encoding="utf-8")
    read = decide_harness_action(
        {"tool_name": "Read", "tool_input": {"file_path": "README.md"}},
        root=tmp_path, harness="t")
    assert read.decision == "observe"
    assert [i for i in read.rule_ids if not i.startswith("GUARD-")] == []
    assert read.selection_evidence == ""
    write = decide_harness_action(
        {"tool_name": "Write",
         "tool_input": {"file_path": "notes.txt", "content": "hi"}},
        root=tmp_path, harness="t")
    assert write.decision == "ask"
    assert "规则库损坏" in write.reason
    assert [i for i in write.rule_ids if not i.startswith("GUARD-")] == []

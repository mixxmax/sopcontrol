"""P1 消费者门 + 规则库损坏分级（收尾补强，非大改）。

1. host_check 规则被选中时：宿主不参与证明通道（host_proofs=None）保持旧行为；
   一旦参与，缺证明即 ask——选择留痕之外，消费者真正影响 gate。
2. 规则库损坏/缺失时：只读可观察（无伪造规则证据），受控写必须 ask/deny。
"""
from __future__ import annotations

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
from sopcontrol.rule_select import decide_action_with_rules


def _rule(rule_id="H-1", *, effect_markers=(), activation=None):
    kw: dict = {}
    if "guard" in effect_markers:
        kw["guard_ids"] = ["GUARD-CONTROLLER-BASH"]
    if "host" in effect_markers:
        kw["consumer_markers"] = ["audit-checker"]
    return Rule(rule_id=rule_id, statement=f"规则{rule_id}",
                modality=Modality.MUST, status=RuleStatus.compiled,
                rule_class="dynamic_sop", source=SourceRef(ref="s"),
                activation=activation or ActivationSelector(), **kw)


def test_host_check_without_proof_asks_when_host_participates():
    rule = _rule("AUDIT-H", effect_markers=("host",),
                 activation=ActivationSelector(actions=["audit"]))
    payload = {"tool_name": "Bash", "tool_input": {"command": "audit --jd"}}
    ctx = {"action": "audit"}
    # 宿主未参与：旧行为（不 ask、不伪装执行）
    plain = decide_action_with_rules([rule], payload, ctx)
    assert plain.decision in ("allow", "observe")
    assert "AUDIT-H" in plain.rule_ids
    # 宿主参与但无证明：ask，点名规则与下一步
    asked = decide_action_with_rules([rule], payload, ctx, host_proofs={})
    assert asked.decision == "ask"
    assert "AUDIT-H" in asked.rule_ids
    assert "缺少有效执行证明" in asked.reason
    assert "host_proofs" in asked.reason
    # 宿主提供证明：恢复旧判定
    from datetime import datetime, timedelta, timezone

    from sopcontrol.action_plane import build_envelope

    _env = build_envelope(payload, harness="t")
    full_proof = {"proof_id": "pf-1", "verdict": "pass",
                  "target": _env.target, "input_digest": _env.input_fingerprint,
                  "expires_at": (datetime.now(timezone.utc)
                                 + timedelta(minutes=5)).isoformat(),
                  "producer": "audit-checker"}
    proved = decide_action_with_rules(
        [rule], payload, ctx, host_proofs={"AUDIT-H": full_proof})
    assert proved.decision == plain.decision
    assert "AUDIT-H" in proved.rule_ids


def _init_project(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    assert main(["init", str(path)]) == 0


def test_corrupt_registry_read_observe_write_ask_or_deny(tmp_path):
    _init_project(tmp_path)
    (tmp_path / ".sopcontrol" / "rules" / "registry.yaml").write_text(
        "rules: [unclosed\n", encoding="utf-8")
    # 只读：可观察，且无伪造的规则证据
    read = decide_harness_action(
        {"tool_name": "Read", "tool_input": {"file_path": "README.md"}},
        root=tmp_path)
    assert read.decision == "observe"
    assert read.rule_ids == []
    assert read.selection_evidence == ""
    # 受控写（自称写入口）：ask，不静默放行
    write = decide_harness_action(
        {"tool_name": "blaster9000", "tool_input": {"path": "/tmp/x"},
         "claimed_side_effects": ["external_write"]},
        root=tmp_path)
    assert write.decision == "ask"
    assert [i for i in write.rule_ids if not i.startswith("GUARD-")] == []
    # 控制器写：deny（与规则库状态无关的硬守卫）
    protected = decide_harness_action(
        {"tool_name": "Write",
         "tool_input": {"file_path": ".sopcontrol/rules/registry.yaml",
                        "content": "x"}},
        root=tmp_path)
    assert protected.decision == "deny"

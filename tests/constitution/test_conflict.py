"""场景10：高影响新规则与历史规则冲突——接受时硬拦。"""
import shutil

import yaml

from sopcontrol.cli import main
from sopcontrol.conflict import find_conflicts
from sopcontrol.model import Modality, Rule, RuleStatus, SourceRef


def _rule(rid, modality, markers, status=RuleStatus.accepted):
    return Rule(
        rule_id=rid,
        statement=f"stmt {rid}",
        modality=modality,
        status=status,
        source=SourceRef(type="manual_seed", ref="t"),
        consumer_markers=list(markers),
    )


def test_opposite_modality_same_marker_is_conflict():
    existing = [_rule("OLD", Modality.MUST, ["ship_gate"])]
    cand = _rule("NEW", Modality.MUST_NOT, ["ship_gate"], status=RuleStatus.proposed)
    hits = find_conflicts(cand, existing)
    assert len(hits) == 1 and hits[0]["other_id"] == "OLD"


def test_supersedes_clears_conflict():
    existing = [_rule("OLD", Modality.MUST, ["ship_gate"])]
    cand = _rule("NEW", Modality.MUST_NOT, ["ship_gate"], status=RuleStatus.proposed)
    cand.supersedes = ["OLD"]
    assert find_conflicts(cand, existing) == []


def test_scenario10_accept_blocked_on_conflict(tmp_path):
    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/ci-deploy", work)
    # 已有 DEPLOY-001 MUST + deploy_gate；加入相反模态并试图 accept
    reg_path = work / ".sopcontrol" / "rules" / "registry.yaml"
    data = yaml.safe_load(reg_path.read_text(encoding="utf-8"))
    data["rules"].append({
        "rule_id": "DEPLOY-BAN",
        "statement": "不得再经 deploy_gate（错误的高影响新规）",
        "modality": "MUST_NOT",
        "status": "proposed",
        "scope": "ci.deploy",
        "owner": "platform",
        "risk": "critical",
        "source": {"type": "manual_seed", "ref": "t"},
        "consumer_markers": ["deploy_gate"],
    })
    reg_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    assert main(["rule", "accept", "DEPLOY-BAN", str(work)]) == 2
    # 不得写进 accepted
    data2 = yaml.safe_load(reg_path.read_text(encoding="utf-8"))
    ban = next(r for r in data2["rules"] if r["rule_id"] == "DEPLOY-BAN")
    assert ban["status"] == "proposed"

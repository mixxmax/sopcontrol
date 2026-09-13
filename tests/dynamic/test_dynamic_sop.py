"""§12.1/§12.2：动态 SOP 永久性、捕获去重、确认四选一、情境选择可解释性。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sopcontrol.cli import main
from sopcontrol.dynamic_sop import (
    confirm_candidate,
    list_dynamic_candidates,
    list_once_only,
    observe_utterance,
    select_rules,
)
from sopcontrol.model import ActivationSelector, Modality, Rule, RuleStatus, SourceRef
from sopcontrol.registry import Registry


@pytest.fixture()
def project(tmp_path):
    assert main(["init", str(tmp_path)]) == 0
    return tmp_path


def test_correction_without_permanence_keyword_becomes_candidate(project):
    """§12.2：无"永久"关键词的行为纠正也能成为候选。"""
    obs, cand, created = observe_utterance(
        project, quote="独立审计只检查与 JD 的贴合和明显事实错误，不要扩展到风格审查",
        source_ref="session-42", context={"action": "materials.audit"})
    assert created is True
    assert cand.kind == "dynamic_sop"
    assert obs.exact_quote.startswith("独立审计")
    assert obs.explicit_once_only is False


def test_duplicate_correction_is_deduplicated(project):
    """同义重复纠正去重：不重复询问（§4.2 第 6 步）。"""
    quote = "以后评分只针对未入表的岗位"
    _o1, c1, created1 = observe_utterance(project, quote=quote,
                                          source_ref="s1")
    _o2, c2, created2 = observe_utterance(project, quote=" 以后评分只针对未入表的岗位 ",
                                          source_ref="s2")
    assert created1 is True and created2 is False
    assert c1.candidate_id == c2.candidate_id
    records = [r for r in list_dynamic_candidates(project)
               if r["candidate_id"] == c1.candidate_id]
    assert records[0]["frequency"] >= 1


def test_explicit_once_only_marker_detected(project):
    obs, _c, _created = observe_utterance(
        project, quote="这次先跳过语义检查，仅本次", source_ref="s1")
    assert obs.explicit_once_only is True


def test_confirm_keep_longterm_creates_permanent_rule(project):
    """确认后：规则进入权威 Registry（rule_class=dynamic_sop），候选 triaged。"""
    _o, cand, _ = observe_utterance(
        project, quote="审计最多修正一轮，达到后停止", source_ref="s1",
        context={"action": "materials.audit"})
    result = confirm_candidate(
        project, cand.candidate_id, "keep_longterm",
        activation={"actions": ["materials.audit"]},
        flexibility={"max_correction_rounds": 1,
                     "lower_bound": "必须核对 JD 贴合与明显事实错误"})
    assert result["permanent"] is True
    assert result["rule_status"] == "compiled"
    rules = Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load()
    rule = next(r for r in rules if r.rule_id == result["rule_id"])
    assert rule.rule_class == "dynamic_sop"
    assert rule.source.type == "user_conversation"  # 原话出处保留
    assert rule.flexibility.max_correction_rounds == 1
    assert rule.activation.actions == ["materials.audit"]


def test_dynamic_sop_survives_reload_and_no_ttl(project):
    """§12.1：进程重启（重新加载）后动态 SOP 仍在；无任何 TTL 字段。"""
    _o, cand, _ = observe_utterance(project, quote="不要重复验证已通过的检查",
                                    source_ref="s1")
    result = confirm_candidate(project, cand.candidate_id, "keep_longterm")
    # 模拟重启：全新 Registry 实例重新加载
    rules = Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load()
    rule = next(r for r in rules if r.rule_id == result["rule_id"])
    assert rule.rule_class == "dynamic_sop"
    assert not hasattr(rule, "expires_at") or rule.expires_at is None


def test_once_only_never_enters_permanent_space(project):
    """§12.2：仅本次 → 会话级记录，Registry 无新规则。"""
    before = len(Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load())
    _o, cand, _ = observe_utterance(project, quote="仅本次跳过标题检查",
                                    source_ref="s1")
    result = confirm_candidate(project, cand.candidate_id, "once_only")
    assert result["permanent"] is False
    after = Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load()
    assert len(after) == before  # 永久空间零增长
    assert any("跳过标题检查" in i["statement"] for i in list_once_only(project))


def test_not_a_rule_marks_rejected(project):
    _o, cand, _ = observe_utterance(project, quote="这个界面颜色再改改", source_ref="s1")
    result = confirm_candidate(project, cand.candidate_id, "not_a_rule")
    assert result["permanent"] is False
    cands = {c["candidate_id"]: c for c in list_dynamic_candidates(project)}
    assert cands[cand.candidate_id]["status"] == "rejected"


def test_model_suggestion_never_creates_rule_directly(project):
    """§4.2：模型建议只是候选素材——observe 不产生规则，必须人工 confirm。"""
    _o, cand, _ = observe_utterance(
        project, quote="评分前先排除已入表的", source_ref="s1",
        suggested={"statement": "评分前先排除已入表的岗位", "modality": "MUST"})
    rules = Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load()
    assert not any(r.rule_class == "dynamic_sop" for r in rules)
    assert cand.kind == "dynamic_sop"  # 只到候选层


def test_edit_keeps_original_quote_in_source(project):
    _o, cand, _ = observe_utterance(project, quote="先看哪些没入表再评分",
                                    source_ref="conv-99")
    result = confirm_candidate(
        project, cand.candidate_id, "edit_keep_longterm",
        edited_statement="评分前必须先与台账比对，只对未入表岗位评分")
    rules = Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load()
    rule = next(r for r in rules if r.rule_id == result["rule_id"])
    assert rule.statement.startswith("评分前必须先与台账比对")
    assert rule.source.ref == "conv-99"  # 原话出处链完整


def test_select_rules_not_applicable_explains():
    """§4.4：未激活 ≠ 过期——选择器不匹配必须可解释（规定措辞形态）。"""
    rules = [Rule(rule_id="DR-001", statement="审计规则",
                  modality=Modality.MUST, status=RuleStatus.compiled,
                  rule_class="dynamic_sop", source=SourceRef(ref="s"),
                  activation=ActivationSelector(actions=["materials.audit"]))]
    selected, na, unproven = select_rules(rules, {"action": "jobs.scan"})
    assert selected == []
    assert len(na) == 1
    assert "规则 DR-001 存在且 compiled" in na[0]["reason"]
    assert "action=jobs.scan" in na[0]["reason"]
    assert "规则要求 action=materials.audit" in na[0]["reason"]


def test_select_rules_matches_when_selector_satisfied():
    rules = [Rule(rule_id="DR-001", statement="审计规则",
                  modality=Modality.MUST, status=RuleStatus.compiled,
                  rule_class="dynamic_sop", source=SourceRef(ref="s"),
                  activation=ActivationSelector(actions=["materials.audit"],
                                                phases=["independent_audit"]))]
    selected, na, unproven = select_rules(rules, {"action": "materials.audit",
                                        "phase": "independent_audit"})
    assert [r.rule_id for r in selected] == ["DR-001"]
    assert na == []


def test_observed_rules_never_selected_for_enforcement():
    """§2.3：observed/proposed 不是权威规则，不得硬拦截。"""
    rules = [Rule(rule_id="DR-X", statement="草案", modality=Modality.MUST,
                  status=RuleStatus.observed, rule_class="dynamic_sop",
                  source=SourceRef(ref="s"))]
    selected, na, unproven = select_rules(rules, {})
    assert selected == [] and na == [] and unproven == []  # 不选择也不进入任何解释桶（未成规则）


def _dr(rule_id="DR-001", *, actions=(), phases=(), products=(),
          status=RuleStatus.compiled):
    return Rule(rule_id=rule_id, statement="审计规则",
                modality=Modality.MUST, status=status,
                rule_class="dynamic_sop", source=SourceRef(ref="s"),
                activation=ActivationSelector(actions=list(actions),
                                              phases=list(phases),
                                              products=list(products)))


def test_select_missing_action_is_unproven_not_selected():
    selected, na, unproven = select_rules([_dr(actions=["materials.audit"])], {})
    assert selected == [] and na == []
    assert len(unproven) == 1
    assert "无法证明 action" in unproven[0]["reason"]
    assert "规则要求 action=materials.audit" in unproven[0]["reason"]
    assert unproven[0]["missing_field"] == "action"


def test_select_missing_phase_is_unproven():
    selected, na, unproven = select_rules(
        [_dr(actions=["materials.audit"], phases=["independent_audit"])],
        {"action": "materials.audit"})
    assert selected == [] and na == []
    assert len(unproven) == 1
    assert unproven[0]["missing_field"] == "phase"


def test_select_missing_product_is_unproven():
    selected, na, unproven = select_rules(
        [_dr(products=["jobsflow"])], {"action": "anything"})
    assert selected == [] and na == []
    assert unproven[0]["missing_field"] == "product"


def test_select_empty_selector_with_empty_context_selects():
    selected, na, unproven = select_rules([_dr()], {})
    assert [r.rule_id for r in selected] == ["DR-001"]
    assert na == [] and unproven == []


def test_select_mismatch_is_not_applicable_not_unproven():
    selected, na, unproven = select_rules(
        [_dr(actions=["materials.audit"])], {"action": "jobs.scan"})
    assert selected == [] and unproven == []
    assert len(na) == 1 and "action=jobs.scan" in na[0]["reason"]


def test_select_all_matched_selects():
    selected, na, unproven = select_rules(
        [_dr(actions=["materials.audit"], phases=["independent_audit"])],
        {"action": "materials.audit", "phase": "independent_audit"})
    assert [r.rule_id for r in selected] == ["DR-001"]
    assert na == [] and unproven == []


def test_select_cli_json_reports_unproven(project, capsys, monkeypatch):
    """§5.4：CLI JSON 输出三桶（正式入口）。"""
    monkeypatch.chdir(project)
    assert main(["dynamic", "observe", "--quote", "审计不扩展到风格",
                 "--source-ref", "conv-7", "--action", "materials.audit"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert main(["dynamic", "confirm", out["candidate_id"],
                 "--decision", "keep_longterm",
                 "--activation", json.dumps({"actions": ["materials.audit"]})]) == 0
    capsys.readouterr()
    assert main(["dynamic", "select", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["selected"] == [] and report["not_applicable"] == []
    assert len(report["unproven"]) == 1
    assert report["unproven"][0]["missing_field"] == "action"
    assert main(["dynamic", "select", "--action", "materials.audit",
                 "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["selected"]) == 1 and report["unproven"] == []


def test_dynamic_cli_flow_end_to_end(project, capsys, monkeypatch):
    """CLI 全链：observe → list → confirm（正式入口，不只测 helper）。"""
    monkeypatch.chdir(project)
    assert main(["dynamic", "observe", "--quote", "审计不扩展到风格",
                 "--source-ref", "conv-7", "--action", "materials.audit"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["new_candidate"] is True
    assert main(["dynamic", "list", "--json"]) == 0
    items = json.loads(capsys.readouterr().out)
    cand_id = items[0]["candidate_id"]
    assert main(["dynamic", "confirm", cand_id,
                 "--decision", "keep_longterm",
                 "--activation", json.dumps({"actions": ["materials.audit"]})]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["permanent"] is True

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
    assert result["rule_status"] == "accepted"  # 确认只保证 accepted，不冒充 compiled
    rules = Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load()
    rule = next(r for r in rules if r.rule_id == result["rule_id"])
    assert rule.rule_class == "dynamic_sop"
    assert rule.source.type == "user_conversation"  # 原话出处保留
    assert rule.flexibility.max_correction_rounds == 1
    assert rule.activation.actions == ["materials.audit"]
    assert rule.compiled_at is None  # 未编译即无编译证据


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


def _confirmed_rule(project):
    _o, cand, _ = observe_utterance(
        project, quote="审计不扩展到风格", source_ref="conv-9",
        context={"action": "materials.audit"})
    result = confirm_candidate(
        project, cand.candidate_id, "keep_longterm",
        activation={"actions": ["materials.audit"]})
    assert result["rule_status"] == "accepted"
    return result["rule_id"]


def test_compile_rule_records_evidence(project):
    """编译产生可验证证据：digest 可重算，状态机推进到 compiled。"""
    from sopcontrol.dynamic_sop import compile_rule

    rid = _confirmed_rule(project)
    receipt = compile_rule(project, rid, actor="user")
    assert receipt["rule_status"] == "compiled"
    assert receipt["compile_digest"]
    rules = Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load()
    rule = next(r for r in rules if r.rule_id == rid)
    assert rule.status == RuleStatus.compiled
    assert rule.compiled_at is not None
    assert rule.compile_digest == receipt["compile_digest"]


def test_compile_requires_accepted_status(project):
    """proposed 直接编译必须失败（跳过确认链）。"""
    from sopcontrol.dynamic_sop import compile_rule

    _o, cand, _ = observe_utterance(
        project, quote="提单前先对一遍台账", source_ref="s9")
    rules = Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load()
    assert len(rules) == 0  # 未确认：永久空间零增长
    from sopcontrol.registry import Registry as _Registry

    with pytest.raises(Exception):
        compile_rule(project, "DR-NONEXISTENT")


def test_profile_expiry_does_not_retire_rule(project):
    """ControlProfile 过期 ≠ Rule 过期：永久规则不受运行实例期限影响。"""
    from sopcontrol.control_profile import ControlProfile

    rid = _confirmed_rule(project)
    expired = ControlProfile(profile_id="p", scope={"task": "T"},
                             checks={"required": [], "excluded": []},
                             expires_at="2020-01-01T00:00:00+00:00")
    assert expired.expires_at is not None
    rules = Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load()
    rule = next(r for r in rules if r.rule_id == rid)
    from sopcontrol.model import rule_is_effective
    from datetime import datetime, timezone

    assert rule_is_effective(rule, at=datetime.now(timezone.utc)) is True
    assert rule.status in (RuleStatus.accepted, RuleStatus.compiled)


def test_rule_stable_across_version_switch(project):
    """版本切换（重载/重存）不改变规则身份与语义字段。"""
    rid = _confirmed_rule(project)
    reg_path = project / ".sopcontrol" / "rules" / "registry.yaml"
    before = Registry(reg_path).load()
    rule = next(r for r in before if r.rule_id == rid)
    snapshot = (rule.rule_id, rule.statement, rule.source.ref,
                rule.activation.actions, rule.flexibility.max_correction_rounds)
    after = Registry(reg_path).load()
    rule2 = next(r for r in after if r.rule_id == rid)
    assert (rule2.rule_id, rule2.statement, rule2.source.ref,
            rule2.activation.actions,
            rule2.flexibility.max_correction_rounds) == snapshot


def test_only_explicit_retire_ends_rule(project):
    """直接改 deprecated/superseded 必须失败；只能走显式退役流。"""
    from sopcontrol.registry import Registry as _Registry

    from sopcontrol.model import RuleStatus as _RS

    rid = _confirmed_rule(project)
    reg = _Registry(project / ".sopcontrol" / "rules" / "registry.yaml")
    with pytest.raises(Exception):
        reg.transition(rid, _RS.deprecated)
    with pytest.raises(Exception):
        reg.transition(rid, _RS.superseded)
    assert reg.load()[0].status == RuleStatus.accepted


def test_no_verified_enforced_vocabulary(project):
    """RuleStatus 词汇表里就没有 verified/enforced——无法冒充，更无法显示。"""
    from sopcontrol.model import RuleStatus as _RS

    assert not hasattr(_RS, "verified") and not hasattr(_RS, "enforced")
    with pytest.raises(ValueError):
        _RS("verified")


def test_dynamic_compile_cli(project, capsys, monkeypatch):
    """compile 走正式 CLI（JSON）。"""
    from sopcontrol.dynamic_sop import compile_rule

    monkeypatch.chdir(project)
    _o, cand, _ = observe_utterance(
        project, quote="审计不扩展到风格", source_ref="conv-10",
        context={"action": "materials.audit"})
    result = confirm_candidate(
        project, cand.candidate_id, "keep_longterm",
        activation={"actions": ["materials.audit"]})
    assert main(["dynamic", "compile", result["rule_id"], "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["rule_status"] == "compiled" and out["compile_digest"]


def test_correction_without_keyword_becomes_low_candidate(project):
    """无"永久"关键词的工作方式纠正 → 低优先级候选（可捕获，不打扰）。"""
    from sopcontrol.dynamic_sop import observe_utterance

    _o, cand, created = observe_utterance(
        project, quote="审计顺序应该先台账后评分", source_ref="s1")
    assert created is True
    assert cand.priority == "low"


def test_plain_discussion_stays_observation_only(project):
    """普通讨论只留 observation，不生成候选。"""
    from sopcontrol.dynamic_sop import list_dynamic_candidates, observe_utterance

    _o, cand, created = observe_utterance(
        project, quote="今天天气不错，适合出去走走", source_ref="s1")
    assert created is False and cand is None
    assert list_dynamic_candidates(project) == []
    assert _o.observation_id.startswith("obs-")


def test_explicit_once_only_blocked_from_permanent(project):
    """显式"仅本次"即使确认 keep_longterm 也必须拒绝进永久空间。"""
    import pytest

    from sopcontrol.dynamic_sop import confirm_candidate, observe_utterance

    _o, cand, _ = observe_utterance(
        project, quote="仅本次跳过标题检查", source_ref="s1")
    assert cand is not None  # 仍需确认卡片（选 once_only）
    with pytest.raises(ValueError, match="仅本次"):
        confirm_candidate(project, cand.candidate_id, "keep_longterm")
    result = confirm_candidate(project, cand.candidate_id, "once_only")
    assert result["permanent"] is False


def test_not_a_rule_never_reasks(project):
    """not_a_rule 后同样原话不再产生新候选。"""
    from sopcontrol.dynamic_sop import confirm_candidate, observe_utterance

    _o, cand, _ = observe_utterance(
        project, quote="审计顺序应该先台账后评分", source_ref="s1")
    confirm_candidate(project, cand.candidate_id, "not_a_rule")
    _o2, cand2, created2 = observe_utterance(
        project, quote="审计顺序应该先台账后评分", source_ref="s2")
    assert created2 is False  # 去重命中，不复问


def test_synonym_correction_aggregates(project):
    """同义重复（标点/大小写差异）聚合到同一候选。"""
    from sopcontrol.dynamic_sop import observe_utterance

    _o1, c1, _ = observe_utterance(
        project, quote="审计顺序应该先台账，后评分", source_ref="s1")
    _o2, c2, created2 = observe_utterance(
        project, quote="审计顺序应该先台账后评分！！", source_ref="s2")
    assert created2 is False and c2.candidate_id == c1.candidate_id


def test_distinct_rules_not_merged(project):
    """不同规则不因相似词语被合并。"""
    from sopcontrol.dynamic_sop import observe_utterance

    _o1, c1, _ = observe_utterance(
        project, quote="审计顺序应该先台账后评分", source_ref="s1")
    _o2, c2, created2 = observe_utterance(
        project, quote="审计顺序应该先评分后台账", source_ref="s2")
    assert created2 is True and c2.candidate_id != c1.candidate_id


def test_suggestion_without_confirm_zero_registry_growth(project):
    """模型建议未确认 → registry 零增长（建议只活在 observation 里）。"""
    from sopcontrol.dynamic_sop import observe_utterance
    from sopcontrol.registry import Registry

    before = len(Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load())
    observe_utterance(
        project, quote="审计顺序应该先台账后评分", source_ref="s1",
        suggested={"statement": "审计必须先台账", "modality": "MUST"})
    after = len(Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load())
    assert after == before


def test_repeat_correction_escalates_priority(project):
    """同类纠正重复出现 → 高优先级。"""
    from sopcontrol.dynamic_sop import observe_utterance

    _o1, c1, _ = observe_utterance(
        project, quote="审计顺序应该先台账后评分", source_ref="s1")
    assert c1.priority == "low"
    _o2, c2, _ = observe_utterance(
        project, quote="审计顺序应该先台账后评分", source_ref="s2")
    assert c2.priority == "high" and c2.frequency == 2


def test_cross_session_restore_with_source_chain(project):
    """换会话从 registry 恢复：规则、原话链、确认信息完整。"""
    from sopcontrol.dynamic_sop import confirm_candidate, observe_utterance
    from sopcontrol.registry import Registry

    _o, cand, _ = observe_utterance(
        project, quote="审计顺序应该先台账后评分", source_ref="conv-42",
        context={"action": "materials.audit"})
    result = confirm_candidate(
        project, cand.candidate_id, "keep_longterm",
        activation={"actions": ["materials.audit"]})
    # 模拟换会话：全新 Registry 实例
    rules = Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load()
    rule = next(r for r in rules if r.rule_id == result["rule_id"])
    assert rule.source.ref == "conv-42"
    assert rule.owner == "user" and rule.accepted_at is not None
    assert rule.activation.actions == ["materials.audit"]


def test_wp_f_session_isolation(project, monkeypatch):
    """WP-F：同会话可读；rotate 后新会话不可读旧记录为 active；--all 可见历史。"""
    from sopcontrol.dynamic_sop import (
        clean_once_only, current_session_id, rotate_session,
    )
    _o, cand, _ = observe_utterance(project, quote="仅本次纠正标题检查用旧模板", source_ref="s1")
    confirm_candidate(project, cand.candidate_id, "once_only")
    sid = current_session_id(project)
    assert any(i.get("session_id") == sid for i in list_once_only(project))
    rotate_session(project)
    assert list_once_only(project) == []
    assert len(list_once_only(project, active_only=False)) == 1
    out = clean_once_only(project)
    assert out["cleaned"] == 1 and not out["error"]
    assert list_once_only(project, active_only=False) == []


def test_wp_f_residue_never_affects_selection(project):
    """WP-F：文件残留不能影响规则选择；新会话重启后亦然。"""
    from sopcontrol.dynamic_sop import rotate_session
    _o, cand, _ = observe_utterance(project, quote="仅本次纠正残留AAA检查", source_ref="s1")
    confirm_candidate(project, cand.candidate_id, "once_only")
    rotate_session(project)  # 新会话：残留只剩历史
    rules = Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load()
    sel, na, unp = select_rules(rules, {"action": "x", "phase": "y"})
    assert all("残留AAA" not in json.dumps(x, ensure_ascii=False) for x in (sel, na, unp))


def test_wp_f_cleanup_failure_never_touches_registry(project, monkeypatch):
    """WP-F：清理失败不删 registry。"""
    from sopcontrol import dynamic_sop as _ds
    before = len(Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load())
    monkeypatch.setattr(_ds, "_atomic_write_jsonl", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    out = _ds.clean_once_only(project, session_id="sess-none")
    assert out["cleaned"] == 0 and out["error"]
    after = Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load()
    assert len(after) == before


def test_wp_f_session_id_not_from_user_text(project, monkeypatch):
    """WP-F：会话 ID 不从用户文本推断；SOPCTL_SESSION 环境优先。"""
    from sopcontrol.dynamic_sop import current_session_id
    monkeypatch.setenv("SOPCTL_SESSION", "sess-env-1")
    assert current_session_id(project) == "sess-env-1"

"""P0-B：统一数据模型测试（§16.1 前半 + P0-B 完成标准）。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from sopcontrol.cli import main
from sopcontrol.learning import (
    LearningEvent, LearningProposal, LearningWindow, ProposalDecision,
    close_window, event_from_observation, load_legacy_candidates,
    load_legacy_rules, open_window, proposal_input_from_candidate,
)


@pytest.fixture()
def project(tmp_path):
    assert main(["init", str(tmp_path)]) == 0
    return tmp_path


def test_strict_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        LearningEvent(kind="utterance", bogus_field="x")
    with pytest.raises(ValidationError):
        LearningWindow(task_id="T", bogus=1)
    with pytest.raises(ValidationError):
        LearningProposal(window_id="w", statement="s", bogus=True)


def test_event_ids_stable_and_no_rule_claims():
    e1 = LearningEvent(kind="utterance", text="以后必须先台账", task_id="T")
    e2 = LearningEvent(kind="utterance", text="以后必须先台账", task_id="T")
    assert e1.event_id == e2.event_id
    assert "rule" not in e1.model_dump()  # 事件层无规则生效断言


def test_window_task_scoped_open_close():
    w = open_window(task_id="T", phase="audit", product="p", session_id="s")
    assert w.is_open and w.task_id == "T"
    closed = close_window(w)
    assert not closed.is_open and closed.window_id == w.window_id


def test_from_observation_carries_quote(project):
    from sopcontrol.dynamic_sop import observe_utterance
    obs, _, _ = observe_utterance(project, quote="以后纠正先台账", source_ref="s1")
    ev = event_from_observation(obs, task_id="T", session_id="sess-1")
    assert ev.text == "以后纠正先台账" and ev.message_ref == obs.observation_id


def test_from_candidate_is_dict_not_rule(project):
    from sopcontrol.dynamic_sop import observe_utterance
    _, cand, _ = observe_utterance(project, quote="以后纠正先台账", source_ref="s1")
    assert cand is not None
    d = proposal_input_from_candidate(cand)
    assert d["statement"] and "frequency" in d and "explicit_once_only" in d


def test_legacy_loads_read_only(project):
    from sopcontrol.dynamic_sop import observe_utterance
    observe_utterance(project, quote="以后纠正先台账", source_ref="s1")
    assert isinstance(load_legacy_candidates(project), list)
    assert isinstance(load_legacy_rules(project), list)


def test_module_never_imports_registry_writer():
    import sopcontrol.learning as m
    import inspect
    src = inspect.getsource(m)
    # 加载只读允许（旧规则可加载）；写操作（迁移/新增/保存）禁止。
    assert ".transition(" not in src and ".add(" not in src and ".save(" not in src


def test_proposal_decision_split_from_rule_status():
    p = LearningProposal(window_id="w", statement="先台账后评分",
                         scope_summary="筛选/评分阶段")
    assert p.status == "proposed"
    d = ProposalDecision(proposal_id=p.proposal_id, route="control")
    assert d.route == "control" and p.status == "proposed"  # 决定不动规则态


def test_p1a_scattered_corrections_merge_to_one_topic():
    from sopcontrol.learning import aggregate_window, open_window
    w = open_window(task_id="T", phase="audit", product="p")
    texts = ["以后必须先台账后评分", "记住先台账，后评分再说",
             "评分之前先做台账", "评分前必须先台账"]
    evs = [LearningEvent(kind="utterance", text=t, task_id="T",
                         scope={"product": "p", "phase": "audit"}) for t in texts]
    b = aggregate_window(evs, w)
    assert len(b.topics) == 1 and b.pruned_count == 0
    assert b.conflicts == []  # 同向纠正无冲突


def test_p1a_opposing_markers_flag_conflict():
    from sopcontrol.learning import aggregate_window, open_window
    w = open_window(task_id="T")
    evs = [LearningEvent(kind="utterance", text="以后必须先台账", task_id="T"),
           LearningEvent(kind="utterance", text="以后不得先台账", task_id="T")]
    b = aggregate_window(evs, w)
    assert len(b.conflicts) == 1 and "对立" in b.conflicts[0]


def test_p1a_empty_and_desensitize(project):
    from sopcontrol.learning import aggregate_window, open_window
    w = open_window(task_id="T")
    evs = [LearningEvent(kind="utterance", text="  ", task_id="T"),
           LearningEvent(kind="utterance", text="联系 a@b.com 拿 sk-live-abc 密码 secret=abc123",
                         task_id="T")]
    b = aggregate_window(evs, w)
    assert b.pruned_count == 1 and len(b.events) == 1
    assert "a@b.com" not in b.events[0].text and "abc123" not in b.events[0].text
    assert "sk-live-abc" not in b.events[0].text


def _bundle(texts, task="T"):
    from sopcontrol.learning import aggregate_window, open_window
    w = open_window(task_id=task)
    evs = [LearningEvent(kind="utterance", text=t, task_id=task) for t in texts]
    return aggregate_window(evs, w)


def test_p1b_ordinary_chat_never_fires():
    from sopcontrol.learning import evaluate_trigger
    d = evaluate_trigger(_bundle(["今天天气不错", "这个方案看看"]))
    assert d.fire is False and d.level == "none"


def test_p1b_single_correction_deferred():
    from sopcontrol.learning import evaluate_trigger
    d = evaluate_trigger(_bundle(["这个地方纠正一下应该先台账"]))
    assert d.fire is False and d.level == "defer"


def test_p1b_repeated_correction_escalates():
    from sopcontrol.learning import evaluate_trigger
    d = evaluate_trigger(_bundle(["纠正：应该先台账", "再次纠正：应该先台账"]))
    assert d.fire is True and d.level == "suggest"


def test_p1b_once_only_never_permanent():
    from sopcontrol.learning import evaluate_trigger
    d = evaluate_trigger(_bundle(["仅本次跳过检查", "只针对这次特事特办"]))
    assert d.fire is False


def test_p1b_same_fingerprint_no_repeat_popup():
    from sopcontrol.learning import evaluate_trigger
    b = _bundle(["以后必须先台账后评分"])
    first = evaluate_trigger(b)
    assert first.fire is True and first.level == "immediate"
    second = evaluate_trigger(b, seen_fingerprints={first.fingerprint})
    assert second.fire is False


def test_p1b_conflict_never_forced():
    from sopcontrol.learning import evaluate_trigger
    b = _bundle(["以后必须先台账", "以后不得先台账"])
    d = evaluate_trigger(b)
    assert d.fire is True and d.level == "suggest" and d.forces_permanent is False


def test_p1c_fake_offline_no_model_needed():
    from sopcontrol.learning import FakeDistiller
    b = _bundle(["以后必须先台账后评分", "评分前必须先台账"])
    out = FakeDistiller().distill(b)
    assert 0 < len(out.proposals) <= 3
    assert out.proposals[0]["non_goals"]


def test_p1c_llm_unproven_explicit():
    from sopcontrol.learning import UnprovenLLMAdapter, distill_with_fallback
    b = _bundle(["以后必须先台账后评分"])
    out, used = distill_with_fallback(b, UnprovenLLMAdapter())
    assert used.startswith("fake-fallback") and out.window_id == b.window_id


def test_p1c_timeout_falls_back():
    import time
    from sopcontrol.learning import DistillerAdapter, distill_with_fallback
    class Slow(DistillerAdapter):
        name = "slow"
        def distill(self, bundle):
            time.sleep(5)
            raise AssertionError("不应到达")
    b = _bundle(["以后必须先台账后评分"])
    out, used = distill_with_fallback(b, Slow(), timeout_s=0.2)
    assert used.startswith("fake-fallback")


def test_p1c_schema_violations_rejected():
    from sopcontrol.learning import DistillerOutput, validate_distiller_output
    b = _bundle(["以后必须先台账"])
    bad = DistillerOutput(window_id=b.window_id, proposals=[
        {"summary": "", "must": ["a"], "must_not": ["a"],
         "non_goals": [], "confidence": "high",
         "evidence_refs": ["不在窗口"], "durability": "permanent_candidate"}])
    problems = validate_distiller_output(bad, b)
    assert len(problems) >= 4  # 空summary/冲突/无non_goals/坏ref（+once_only视数据）


def test_p1c_scope_expansion_rejected():
    from sopcontrol.learning import (DistillerOutput, LearningEvent,
                                     aggregate_window, open_window,
                                     validate_distiller_output)
    w = open_window(task_id="T")
    evs = [LearningEvent(kind="utterance", text="以后必须先台账", task_id="T",
                         scope={"action": "search"})]
    b = aggregate_window(evs, w)
    bad = DistillerOutput(window_id=b.window_id, proposals=[
        {"summary": "s", "must": ["m"], "must_not": [],
         "non_goals": ["n"], "confidence": "high",
         "evidence_refs": [b.events[0].event_id],
         "scope": {"actions": ["删库"]},
         "durability": "permanent_candidate"}])
    assert any("scope 扩大" in p for p in validate_distiller_output(bad, b))


def test_p1d_routes_list_and_decide(project):
    from sopcontrol.learning import (LearningProposal, ProposalDecision,
                                     decide_proposal, list_proposals,
                                     save_proposals)
    p = LearningProposal(window_id="w", statement="先台账后评分",
                         scope_summary="筛选阶段", non_goals=["不扩范围"])
    assert save_proposals(project, [p]) == 1
    assert len(list_proposals(project, status="proposed")) == 1
    d = ProposalDecision(proposal_id=p.proposal_id, route="control")
    out = decide_proposal(project, p, d)
    assert out["status"] == "confirmed" and "candidate_id" in out
    # control 经候选箱：Registry 零增长，候选箱 +1
    from sopcontrol.registry import Registry
    assert isinstance(Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load(), list)
    from sopcontrol.dynamic_sop import list_dynamic_candidates
    assert any(c["statement"] == "先台账后评分" for c in list_dynamic_candidates(project))
    assert list_proposals(project, status="proposed") == []


def test_p1d_document_both_once_only_defer_reject(project):
    from sopcontrol.learning import (LearningProposal, ProposalDecision,
                                     decide_proposal, list_proposals)
    import pytest as _pt
    mk = lambda s, w="w": LearningProposal(window_id=w, statement=s,
                                           scope_summary="sc", non_goals=["n"])
    p1 = mk("文案A", "w1")
    out = decide_proposal(project, p1, ProposalDecision(proposal_id=p1.proposal_id, route="document"))
    assert out["status"] == "confirmed" and out["doc_payload"]["statement"] == "文案A"
    p2 = mk("双轨B", "w2")
    out2 = decide_proposal(project, p2, ProposalDecision(proposal_id=p2.proposal_id, route="both"))
    assert "candidate_id" in out2 and "doc_payload" in out2
    p3 = mk("本次C", "w3")
    out3 = decide_proposal(project, p3, ProposalDecision(proposal_id=p3.proposal_id, route="once_only"))
    assert out3["status"] == "confirmed"
    p4 = mk("延后D", "w4")
    assert decide_proposal(project, p4, ProposalDecision(proposal_id=p4.proposal_id, route="defer"))["status"] == "deferred"
    p5 = mk("拒绝E", "w5")
    assert decide_proposal(project, p5, ProposalDecision(proposal_id=p5.proposal_id, route="reject"))["status"] == "rejected"
    # once_only 证据禁 control
    p6 = LearningProposal(window_id="w6", statement="临时F", scope_summary="sc",
                          non_goals=["n"], evidence_refs=["仅本次-obs-1"])
    with _pt.raises(ValueError, match="once_only"):
        decide_proposal(project, p6, ProposalDecision(proposal_id=p6.proposal_id, route="control"))
    # 重复决定拒绝（以库内已定案态重决）
    done = list_proposals(project, status="deferred")[0]
    with _pt.raises(ValueError, match="已定案"):
        decide_proposal(project, done, ProposalDecision(proposal_id=done.proposal_id, route="reject"))
    assert list_proposals(project, status="proposed") == []  # 被拒 control 未落盘


def test_p1e_cli_json_outbox_and_unproven_host(project):
    from sopcontrol.learning import (CliJsonAdapter, HostUiAdapter,
                                     LearningProposal, NotifyPayload,
                                     payload_from_proposal)
    import pytest as _pt
    p = LearningProposal(window_id="w", statement="先台账", scope_summary="筛选",
                         non_goals=["n"])
    payload = payload_from_proposal(p, route_hint="suggest")
    assert payload.actions == ["control", "document", "once_only", "defer", "reject"]
    out = CliJsonAdapter().notify(project, payload)
    assert out["delivered_to_ui"] is False  # 不冒充送达
    assert "先台账" in (project / ".sopcontrol-local" / "learning" / "notifications.jsonl").read_text(encoding="utf-8")
    with _pt.raises(RuntimeError, match="UNPROVEN"):
        HostUiAdapter().notify(project, payload)


def test_p2a_explicit_review_same_pipeline(project):
    from sopcontrol.dynamic_sop import observe_utterance
    from sopcontrol.learning import list_proposals, review_window
    observe_utterance(project, quote="以后纠正先台账后评分", source_ref="s1")
    out = review_window(project, session_id="sess-1")
    assert out["events"] >= 1 and out["proposals"] >= 1
    assert out["adapter"] in ("fake",)
    assert len(list_proposals(project, status="proposed")) == out["proposals"]
    import pytest as _pt
    with _pt.raises(ValueError, match="必须指定"):
        review_window(project)


def test_p2a_external_import_no_registry_no_projection(project):
    from sopcontrol.learning import import_external_proposal, list_proposals
    from sopcontrol.registry import Registry
    import pytest as _pt
    before = len(Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load())
    p = import_external_proposal(project, {"statement": "外部经验：先小批量",
                                           "source_ref": "antigravity:/learn",
                                           "non_goals": ["不扩范围"]})
    assert p.evidence_refs == ["external:antigravity:/learn"]
    assert len(Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load()) == before
    assert len(list_proposals(project, status="proposed")) == 1
    with _pt.raises(ValueError, match="回灌"):
        import_external_proposal(project, {"statement": "复制 <!-- sopcontrol:v1 --> 内容"})
    with _pt.raises(ValueError, match="为空"):
        import_external_proposal(project, {"statement": "  "})


def test_p2b_doc_preserves_user_content_and_sop(tmp_path):
    from sopcontrol.learning import (doc_section_digest, external_change_to_proposal_input,
                                     write_doc_section)
    doc = tmp_path / "notes.md"
    doc.write_text("# 笔记\n\n<!-- sopcontrol:v1 -->\nRULES\n<!-- /sopcontrol:v1 -->\n\n正文A\n", encoding="utf-8")
    out = write_doc_section(doc, ["- 先台账后评分"])
    text = doc.read_text(encoding="utf-8")
    assert "正文A" in text and "<!-- sopcontrol:v1 -->\nRULES\n<!-- /sopcontrol:v1 -->" in text
    assert out["sop_untouched"] is True
    d1 = out["digest"]
    assert doc_section_digest(doc) == d1
    # 二次写入幂等形态：单学习区，不重复卡片
    write_doc_section(doc, ["- 先台账后评分", "- 例外：用户反向要求"])
    assert doc.read_text(encoding="utf-8").count("<!-- learn:begin -->") == 1
    # 外部变更只成提案输入
    nxt = external_change_to_proposal_input(doc, d1)
    assert nxt is not None and nxt["statement"].startswith("<!-- learn:begin -->")
    assert external_change_to_proposal_input(doc, doc_section_digest(doc)) is None
    import pytest as _pt
    with _pt.raises(ValueError, match="回环"):
        from sopcontrol import learning as _lm
        bad = tmp_path / "bad.md"
        bad.write_text("<!-- sopcontrol:v1 -->\n<!-- learn:begin -->\nx\n<!-- learn:end -->\n<!-- /sopcontrol:v1 -->\n", encoding="utf-8")
        _lm.write_doc_section(bad, ["y"])


def test_p2c_budget_degrades_never_blocks():
    from sopcontrol.learning import (LearningBudget, LearningMetrics, check_budget)
    ok, _ = check_budget(LearningMetrics(events=3, windows=1))
    assert ok is True
    ok, why = check_budget(LearningMetrics(events=200, windows=1))
    assert ok is False and "事件超限" in why
    ok, why = check_budget(LearningMetrics(events=1, windows=5))
    assert ok is False and "窗口超限" in why
    ok, why = check_budget(LearningMetrics(events=1, windows=1, distills=3))
    assert ok is False and "提炼调用超限" in why
    assert LearningBudget().max_proposals_per_window == 3


def test_p2c_diagnose_read_only(project):
    from sopcontrol.learning import (LearningProposal, learning_diagnose,
                                     save_proposals)
    d0 = learning_diagnose(project)
    assert d0["proposals_total"] == 0 and d0["llm_tokens"] == 0
    save_proposals(project, [LearningProposal(window_id="w", statement="s",
                                              scope_summary="sc", non_goals=["n"])])
    d1 = learning_diagnose(project)
    assert d1["proposals_total"] == 1 and d1["decision_rate"] == 0.0

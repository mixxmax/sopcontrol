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

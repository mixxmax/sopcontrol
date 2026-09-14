"""PROMPT-A P3：learn CLI 全链路（自动与显式同一管道）。"""
from __future__ import annotations

import json

from sopcontrol.cli import main


def _project(tmp_path):
    assert main(["init", str(tmp_path)]) == 0
    return tmp_path


def test_learn_review_list_show_decide(tmp_path, capsys):
    from sopcontrol.dynamic_sop import observe_utterance
    root = _project(tmp_path)
    capsys.readouterr()
    observe_utterance(
        root,
        quote="以后纠正先台账后评分",
        source_ref="s1",
        context={"session_id": "sess-1", "task_id": "task-1"},
    )
    assert main(["learn", "review", "--session", "sess-1", str(root)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["proposals"] >= 1 and out["events"] >= 1
    assert main(["learn", "list", "--json", str(root)]) == 0
    items = json.loads(capsys.readouterr().out)
    pid = items[0]["proposal_id"]
    assert items[0]["status"] == "proposed"
    assert main(["learn", "show", pid, str(root)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["proposal_id"] == pid
    assert main(["learn", "decide", pid, "--route", "defer", str(root)]) == 0
    decided = json.loads(capsys.readouterr().out)
    assert decided["status"] == "deferred"


def test_learn_decide_control_requires_user_confirmation(tmp_path, capsys):
    """CLI：无 confirmation 时 control 返回 needs_user；handoff 核销后才 compiled。"""
    from sopcontrol.learning import LearningProposal, save_proposals
    root = _project(tmp_path)
    capsys.readouterr()
    p = LearningProposal(window_id="w", statement="以后必须先筛选再评分",
                         scope_summary="scan", non_goals=["n"])
    save_proposals(root, [p])
    rc = main(["learn", "decide", p.proposal_id, "--route", "control", str(root)])
    assert rc == 3
    challenge = json.loads(capsys.readouterr().out)
    assert challenge["status"] == "needs_user"
    assert challenge.get("confirmation_id")
    assert "confirmation_secret" not in challenge
    conf_id = challenge["confirmation_id"]
    assert main([
        "learn", "decide", p.proposal_id, "--route", "control",
        "--confirmation-id", conf_id, str(root),
    ]) == 0
    decided = json.loads(capsys.readouterr().out)
    assert decided["status"] == "confirmed"
    assert decided.get("rule_status") == "compiled"
    assert "secret" not in json.dumps(decided).lower() or "secret_sha" not in json.dumps(decided)


def test_learn_review_requires_scope(tmp_path, capsys):
    root = _project(tmp_path)
    capsys.readouterr()
    assert main(["learn", "review", str(root)]) == 2


def test_learn_ingest_and_notify(tmp_path, capsys):
    root = _project(tmp_path)
    capsys.readouterr()
    payload = json.dumps({"statement": "外部经验：先小批量",
                          "source_ref": "antigravity:/learn",
                          "non_goals": ["不扩范围"]})
    assert main(["learn", "ingest", "--json-data", payload, str(root)]) == 0
    pid = json.loads(capsys.readouterr().out)["proposal_id"]
    assert main(["learn", "notify", pid, "--json", str(root)]) == 0
    card = json.loads(capsys.readouterr().out)
    assert card["notification_type"] == "learning_proposal"
    assert card["interrupt"] is False
    assert card["available_decisions"] == ["control", "document", "once_only",
                                           "defer", "reject"]
    assert "尚未生效" in card["note"]
    assert main(["learn", "notify", pid, str(root)]) == 0
    outbox = json.loads(capsys.readouterr().out)
    assert outbox["adapter"] == "cli-json"
    assert main(["learn", "diagnose", str(root)]) == 0
    diag = json.loads(capsys.readouterr().out)
    assert diag["proposals_total"] == 1

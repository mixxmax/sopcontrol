"""场景1：讨论不是实施授权；候选不进注册表；分类纯函数。"""
import builtins
import json
import shutil

import yaml

from sopcontrol.cli import main
from sopcontrol.harness import check_tool_call
from sopcontrol.intent import (
    classify_utterance,
    load_session_intent,
    process_conversation,
)


def test_classify_is_pure(monkeypatch):
    def no_open(*a, **k):
        raise AssertionError("意图分类不得做 I/O")

    monkeypatch.setattr(builtins, "open", no_open)
    assert classify_utterance("我们只讨论方案，不要修改代码").intent == "discuss_only"
    assert classify_utterance("可以改了，开始实现").intent == "implement"
    assert classify_utterance("以后必须先预览再确认").intent == "rule_candidate"


def test_discuss_only_denies_writes():
    d = check_tool_call(
        {"tool_name": "Write", "tool_input": {"file_path": "src/x.py"}},
        session_intent="discuss_only",
    )
    assert d.permissionDecision == "deny"
    assert "discuss_only" in d.reason or "讨论" in d.reason

    d = check_tool_call(
        {"tool_name": "edit", "tool_input": {"file_path": "src/x.py"}},
        session_intent="discuss_only",
    )
    assert d.permissionDecision == "deny"

    # 非写工具在 discuss_only 下仍可观察放行（读/讨论）
    d = check_tool_call(
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
        session_intent="discuss_only",
    )
    assert d.permissionDecision == "allow"


def test_scenario1_conversation_intake_and_harness(tmp_path, capsys):
    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/jobflow-preview", work)
    conv = work / "chat.txt"
    conv.write_text(
        "我们先只讨论，不要修改代码。\n"
        "以后必须先预览再确认再入表。\n",
        encoding="utf-8",
    )

    assert main(["intake", str(work), "--conversation", str(conv)]) == 0
    out = capsys.readouterr().out
    assert "discuss_only" in out

    session = load_session_intent(work)
    assert session.intent == "discuss_only"

    candidates = yaml.safe_load(
        (work / ".sopcontrol" / "rules" / "candidates.yaml").read_text(encoding="utf-8")
    )
    assert any("预览" in c["statement"] for c in candidates)
    assert all(c["status"] == "observed" for c in candidates)
    # Candidate 永不进注册表
    registry = (work / ".sopcontrol" / "rules" / "registry.yaml").read_text(encoding="utf-8")
    assert "先预览再确认再入表" not in registry

    # 模型试图改代码 → harness-check 拒绝
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "src/gateway.py"}})
    assert main(["harness-check", str(work), "--payload", payload]) == 0
    decision = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"

    # 解除锁定后可写普通文件
    assert main(["intent", "clear", str(work)]) == 0
    capsys.readouterr()  # 丢掉 clear 的提示，避免污染 JSON
    assert main(["harness-check", str(work), "--payload", payload]) == 0
    decision = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert decision["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_implement_utterance_clears_discuss(tmp_path):
    root = tmp_path
    (root / ".sopcontrol").mkdir()
    process_conversation(root, "先只讨论，不要改代码")
    assert load_session_intent(root).intent == "discuss_only"
    process_conversation(root, "可以改了，开始实现")
    assert load_session_intent(root).intent == "unknown"

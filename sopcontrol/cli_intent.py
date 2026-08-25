"""CLI commands — cli_intent.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from .cli_common import *  # noqa: F403
from .audit import run_audit, run_task_verify
from .harness import PUSH_RE, HookDecision
from .ledger import Ledger
from .model import Modality, RiskLevel, Rule, RuleStatus, SourceRef
from .registry import Registry, RegistryError
from .repair import RepairError, list_repairs, open_repair
from .task import Contract, TaskRecord, TaskStore, evaluate_transition, normalize_relpath, takeover_pack
from .verdict import evaluate_rule
from plugins import DETECTORS, SENSORS



def cmd_intake(args) -> int:
    """意图编译器 v0：文档 MUST 句和/或对话摘录 → Candidate（observed，不写终态）。"""
    from plugins import DETECTORS, SENSORS

    from .intent import process_conversation

    root = _project(args.path)

    if getattr(args, "conversation", None):
        text = Path(args.conversation).read_text(encoding="utf-8")
        summary = process_conversation(root, text)
        print(
            f"对话意图处理：有效语句 {summary['utterances']}，"
            f"新增候选 {summary['candidates_added']}，"
            f"会话意图={summary['final_intent']}"
        )
        for note in summary["notes"]:
            print(f"  · {note}")
        if summary["final_intent"] == "discuss_only":
            print("  写工具将被 harness-check 拒绝，直至解除讨论锁定")
        # 对话路径可单独运行；未要求文档扫描时到此结束
        if not getattr(args, "with_docs", False):
            return 0

    report = run_audit(root, SENSORS, DETECTORS, persist=False)
    registry_path = root / ".sopcontrol" / "rules" / "registry.yaml"
    known_statements = {r.statement for r in Registry(registry_path).load()}

    candidates_path = root / ".sopcontrol" / "rules" / "candidates.yaml"
    existing = []
    if candidates_path.exists():
        existing = yaml.safe_load(candidates_path.read_text(encoding="utf-8")) or []

    seq = len(existing) + 1
    new = []
    for ev in report.evidence:
        if ev.kind != "doc_scan.must_statement":
            continue
        statement = str(ev.observed).strip().lstrip("- ").rstrip("。.")
        if any(c.get("statement") == statement for c in existing) or statement in known_statements:
            continue
        new.append({
            "candidate_id": f"CAND-{seq:03d}",
            "statement": statement,
            "suggested_modality": _suggest_modality(statement),
            "source": {"type": "document", "ref": ev.subject},
            "status": "observed",
            "note": "由 doc_scan 提取；晋升需显式 sopctl rule add（Candidate 不写终态）",
        })
        seq += 1

    if not new:
        print("没有新的候选规则（文档 MUST 句已全部登记或在候选中）")
        return 0
    candidates_path.write_text(
        yaml.safe_dump(existing + new, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(f"提取 {len(new)} 条候选规则 → {candidates_path}（status=observed，未进注册表）")
    for c in new:
        print(f"  {c['candidate_id']}: {c['statement'][:50]}  ← {c['source']['ref']}")
    print("晋升方式: sopctl rule add --statement '...'（人工确认后进入 registry）")
    return 0



def cmd_intent(args) -> int:
    """查看或清除会话意图（discuss_only 锁定）。"""
    from .intent import clear_session_intent, load_session_intent

    root = _project(args.path)
    if args.sub == "show":
        session = load_session_intent(root)
        print(yaml.safe_dump(session.model_dump(mode="json"), allow_unicode=True, sort_keys=False).strip())
        return 0
    if args.sub == "clear":
        clear_session_intent(root)
        print("已清除会话意图（discuss_only 锁定解除）")
        return 0
    return 2


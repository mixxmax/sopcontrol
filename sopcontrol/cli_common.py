"""CLI 共用：路径、钩子模板、小工具。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from .audit import run_audit, run_task_verify
from .harness import PUSH_RE, HookDecision
from .ledger import Ledger
from .model import Modality, RiskLevel, Rule, RuleStatus, SourceRef
from .registry import Registry, RegistryError
from .repair import RepairError, list_repairs, open_repair
from .task import (
    Contract,
    TaskRecord,
    TaskStore,
    evaluate_transition,
    normalize_relpath,
    takeover_pack,
)
from .verdict import evaluate_rule

"""sopctl 命令行：init / rule / audit / explain。

audit 默认是观察模式（L0/L1，只建议不阻断，退出码 0）；
--strict 供 CI 终态门使用：存在 gap/fail 即退出码 1（ Haft check 语义）。
"""
__all__ = [
    "HOOK_MARKER",
    "HOOK_TEMPLATE",
    "NEGATIVE_KEYWORDS",
    "OPENCODE_PLUGIN_TEMPLATE",
    "_suggest_modality",
    "run_gate",
    "_write_profile",
    "_parse_fields",
    "_task_decide",
    "_project",
]

HOOK_MARKER = "# sopcontrol-hook v1"
HOOK_TEMPLATE = f"""#!/bin/sh
{HOOK_MARKER}
# 终态门：fail 判定或账本篡改则阻断 push（gap 仅警告）
exec sopctl gate "$(git rev-parse --show-toplevel)"
"""
NEGATIVE_KEYWORDS = ("不得", "禁止", "must not", "mustn't", "never ")
OPENCODE_PLUGIN_TEMPLATE = '''// sopcontrol-hook v1 (marker) — sopctl hook opencode 生成；决策权在本地控制器，插件只是执行器
import {{ execFileSync }} from "node:child_process";

const PY = {python_json};
const PROJECT = {project_json};

export const SopControl = async () => {{
  return {{
    "tool.execute.before": async (input, output) => {{
      let payload = null;
      if (input.tool === "bash") {{
        payload = {{ tool_name: "Bash", tool_input: {{ command: output.args.command }} }};
      }} else if (input.tool === "edit" || input.tool === "write") {{
        payload = {{ tool_name: "Write", tool_input: {{ file_path: output.args.filePath ?? output.args.file_path }} }};
      }}
      if (!payload) return; // 非受控工具：观察，不阻断
      let decision;
      try {{
        const out = execFileSync(PY, ["-m", "sopcontrol.cli", "harness-check", "--payload",
          JSON.stringify(payload), PROJECT], {{ encoding: "utf8" }});
        decision = JSON.parse(out);
      }} catch (e) {{
        throw new Error("[sopcontrol] harness-check 不可用，fail-closed: " + e.message);
      }}
      const d = (decision.hookSpecificOutput ?? {{}});
      if (d.permissionDecision === "deny") throw new Error("[sopcontrol] 拒绝: " + d.permissionDecisionReason);
      if (d.permissionDecision === "ask") throw new Error("[sopcontrol] 需人工确认: " + d.permissionDecisionReason);
    }},
  }};
}};
'''


def _suggest_modality(statement: str) -> str:
    low = statement.lower()
    return "MUST_NOT" if any(k in low for k in NEGATIVE_KEYWORDS) else "MUST"



def run_gate(root: Path) -> int:
    """终点门核心逻辑（cmd_gate 与 sopctl wrap 共用）。"""
    from plugins import DETECTORS, SENSORS

    try:
        report = run_audit(root, SENSORS, DETECTORS, persist=True)
    except Exception as exc:  # 门自身故障必须阻断，不允许静默放行
        print(f"gate: 审计失败，fail-closed 阻断（{exc}）", file=sys.stderr)
        return 1

    ledger = Ledger(root / ".sopcontrol" / "evidence" / "ledger.jsonl")
    tampered = ledger.path.exists() and not ledger.verify()
    fails = [v for v in report.verdicts if v.status == "fail"]
    gaps = [v for v in report.verdicts if v.status == "gap"]

    for v in gaps:
        print(f"GAP(警告，不阻断) {v.rule_id}: {v.reason[:80]}")
    for v in fails:
        print(f"FAIL(阻断) {v.rule_id}: {v.reason[:100]}", file=sys.stderr)

    if tampered:
        print("FAIL(阻断): 证据账本被篡改或损坏（运行 sopctl doctor 复核）", file=sys.stderr)

    if fails or tampered:
        print(f"gate: 已阻断——fail {len(fails)} 项，账本{'损坏' if tampered else '完整'}", file=sys.stderr)
        return 1
    print(f"gate: 通过（gap 警告 {len(gaps)} 项未阻断，治理阶梯见 DESIGN.md §8）")
    return 0



def _write_profile(root: Path) -> None:
    from .harness import HARNESS_PROFILES

    path = Path(root) / ".sopcontrol" / "harness-profile.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(HARNESS_PROFILES, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )



def _parse_fields(raw: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in raw or []:
        if "=" not in item:
            raise ValueError(f"--field 需要 key=value 形式，收到 {item!r}")
        key, _, val = item.partition("=")
        if not key.strip():
            raise ValueError(f"--field 键为空: {item!r}")
        out[key.strip()] = val
    return out



def _task_decide(
    root: Path,
    task_id: str,
    action: str,
    args=None,
    changed_paths=None,
    provided_fields=None,
):
    """task 子命令共用骨架：载入 → 纯函数判定 → 应用 → 打印。返回退出码。"""
    from plugins import DETECTORS, SENSORS

    store = TaskStore(root)
    task = store.load(task_id)
    known = {r.rule_id for r in Registry(root / ".sopcontrol" / "rules" / "registry.yaml").load()}
    if action == "verify":
        decision = run_task_verify(root, SENSORS, DETECTORS, task)
    else:
        decision = evaluate_transition(
            task, action,
            changed_paths=changed_paths,
            provided_fields=provided_fields,
            known_rule_ids=known,
        )
    task = store.apply(task, decision, action, changed_paths=changed_paths)
    mark = "迁移" if decision.allowed and decision.to_status else "拒绝"
    print(f"{mark}: {task_id} {task.status.value} (r{task.revision})")
    print(f"  理由: {decision.reason}")
    print(f"  下一步: {decision.next_action}")
    return 0



def _project(path: str) -> Path:
    return Path(path).resolve()


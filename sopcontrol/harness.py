"""Harness 适配（B4）：把控制平面接到真实 coding harness 的工具调用入口。

Claude Code PreToolUse 协议。决策是纯函数（无 I/O，宪法测试守卫）；
终点门上下文（block/warn/clean）由调用方注入——推送是唯一需要门上下文的动作。

策略（确定性）：
- 控制器文件（.sopcontrol/）不允许经普通写入口或非 sopctl 命令触碰（信任根，手册 9.3/12.2）；
- --no-verify 一律拒绝（R6 绕过家族）；
- git push 走终点门：block→deny，warn(gap)→ask，clean→allow。
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel

PROTECTED_DIR = ".sopcontrol"

PUSH_RE = re.compile(r"(^|&&|;|\|\||\|)\s*git push\b")
_CLAUDE_TOOLS_WRITE = {"Write", "Edit", "MultiEdit"}


class HookDecision(BaseModel):
    permissionDecision: Literal["allow", "deny", "ask"]
    reason: str

    def claude_payload(self) -> dict:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": self.permissionDecision,
                "permissionDecisionReason": self.reason,
            }
        }


def _deny(reason: str) -> HookDecision:
    return HookDecision(permissionDecision="deny", reason=reason)


def _allow(reason: str) -> HookDecision:
    return HookDecision(permissionDecision="allow", reason=reason)


def check_tool_call(payload: dict, gate_status: Optional[str] = None) -> HookDecision:
    """gate_status: None=与终点门无关 / "block" / "warn" / "clean"。纯函数。"""
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}

    if tool in _CLAUDE_TOOLS_WRITE:
        file_path = str(tool_input.get("file_path") or tool_input.get("path") or "")
        if file_path and any(part == PROTECTED_DIR for part in file_path.replace("\\", "/").split("/")):
            return _deny(
                f"控制器文件 {file_path} 不允许经普通写入口修改：规则/账本/任务只能通过 "
                f"sopctl 命令变更（信任根，手册 9.3）；规则变更请走 sopctl rule 流程"
            )
        return _allow("普通文件写入，不在受控清单")

    if tool == "Bash":
        command = str(tool_input.get("command") or "")

        if "--no-verify" in command:
            return _deny("拒绝 --no-verify：绕过验证钩子属于已登记绕过家族 R6，一律阻断")

        touches_controller = PROTECTED_DIR in command and "sopctl" not in command
        if touches_controller:
            return _deny(
                f"命令直接触碰 {PROTECTED_DIR}/ 但未走 sopctl：控制器状态只能经 sopctl 变更；"
                f"读取用 sopctl explain/show，变更用对应子命令"
            )

        if PUSH_RE.search(command):
            if gate_status is None:
                return _deny("git push 未经过终点门评估（上下文缺失）：fail-closed 拒绝；请经 sopctl hook 安装的入口执行")
            if gate_status == "block":
                return _deny(
                    "终点门阻断：存在 fail 判定或账本损坏，禁止推送。运行 sopctl gate 查看具体规则与理由"
                )
            if gate_status == "warn":
                return HookDecision(
                    permissionDecision="ask",
                    reason="终点门警告：存在 gap（规则未接线或未测试）。建议先 sopctl gate 复核；确要推送请人工确认",
                )
            if gate_status == "clean":
                return _allow("终点门通过：无 fail 判定，账本完整")

        return _allow("不在受控动作清单（观察模式）")

    return _allow(f"工具 {tool or '未知'} 不在受控范围（观察模式）")


def gate_status_for_push(root) -> Optional[str]:
    """为 git push 计算终点门上下文。只有推送需要——其他动作不付审计成本。"""
    from .audit import run_audit
    from .ledger import Ledger

    from plugins import DETECTORS, SENSORS

    try:
        report = run_audit(root, SENSORS, DETECTORS, persist=False)
    except Exception:
        return "block"  # 门无法审计 = fail-closed
    ledger = Ledger(root / ".sopcontrol" / "evidence" / "ledger.jsonl")
    if (ledger.path.exists() and not ledger.verify()) or any(
        v.status == "fail" for v in report.verdicts
    ):
        return "block"
    if any(v.status == "gap" for v in report.verdicts):
        return "warn"
    return "clean"

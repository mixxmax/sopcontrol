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
# 控制器自身安装物：agent 卸掉自己的项圈 = 提权，一律拒绝（人工可手工移除）
PROTECTED_HINTS = (".opencode/plugins/sopcontrol", ".claude/settings.json")

PUSH_RE = re.compile(r"(^|&&|;|\|\||\|)\s*git push\b")

# 能力画像（手册 5.9）：不同 harness 得到不同控制强度，如实记录，不假装一致
HARNESS_PROFILES = {
    "claude": {
        "interception": "runtime: PreToolUse hook (JSON 决策)",
        "terminal": "git pre-push 钩子 + CI gate",
        "live_verified": False,
        "note": "本环境 claude API key 无效（401），协议契约由测试覆盖",
    },
    "opencode": {
        "interception": "runtime: .opencode/plugins tool.execute.before（抛错阻断）",
        "terminal": "git pre-push 钩子 + CI gate",
        "live_verified": True,
        "live_evidence": "2026-08-24 沙箱演习：真实模型 Edit .sopcontrol 被拒，文件未改，模型转述理由后停止",
    },
    "codex": {
        "interception": "none（0.147 无工具调用前钩子）",
        "terminal": "git pre-push 钩子 + CI gate + sopctl wrap codex（事后门）",
        "advisory": "AGENTS.md 规则投影（sopctl project codex）",
        "live_verified": True,
        "live_evidence": "2026-08-24 沙箱演习：codex 创建文件后 wrap 事后门阻断（fail 规则），退出码 1；模型曾主动尝试按投影运行 sopctl gate",
    },
}


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


def check_tool_call(
    payload: dict,
    gate_status: Optional[str] = None,
    session_intent: Optional[str] = None,
) -> HookDecision:
    """gate_status: None=与终点门无关 / "block" / "warn" / "clean"。纯函数。

    session_intent: 由调用方注入（CLI 读 session-intent.yaml）；discuss_only 时拒绝写工具。
    工具名大小写归一（Claude 用 Bash/Write，OpenCode 用 bash/edit/write）。
    """
    tool = str(payload.get("tool_name") or "").lower()
    tool_input = payload.get("tool_input") or {}
    intent = session_intent or str(payload.get("session_intent") or "")

    if tool in {"write", "edit", "multiedit"}:
        if intent == "discuss_only":
            return _deny(
                "当前会话意图为 discuss_only（用户明确只讨论不修改）：拒绝写文件。"
                "讨论不是实施授权（14.1 场景1）；若要改代码请先解除讨论锁定"
                "（说出实施意图或 sopctl intent clear）"
            )
        file_path = str(
            tool_input.get("file_path") or tool_input.get("filePath")
            or tool_input.get("path") or ""
        )
        if file_path and any(part == PROTECTED_DIR for part in file_path.replace("\\", "/").split("/")):
            return _deny(
                f"控制器文件 {file_path} 不允许经普通写入口修改：规则/账本/任务只能通过 "
                f"sopctl 命令变更（信任根，手册 9.3）；规则变更请走 sopctl rule 流程"
            )
        if file_path and any(hint in file_path.replace("\\", "/") for hint in PROTECTED_HINTS):
            return _deny(
                f"{file_path} 是 sopctl 安装的拦截组件：移除自身项圈属于提权动作，"
                f"需要人工执行（手册 12.2）"
            )
        return _allow("普通文件写入，不在受控清单")

    if tool == "bash":
        command = str(tool_input.get("command") or "")

        if "--no-verify" in command:
            return _deny("拒绝 --no-verify：绕过验证钩子属于已登记绕过家族 R6，一律阻断")

        touches_controller = (
            (PROTECTED_DIR in command or any(hint in command for hint in PROTECTED_HINTS))
            and "sopctl" not in command
        )
        if touches_controller:
            return _deny(
                f"命令直接触碰控制器状态或拦截组件（{PROTECTED_DIR}/、opencode 插件、claude 钩子配置）"
                f"但未走 sopctl：一切经 sopctl 子命令；移除拦截组件需人工执行"
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

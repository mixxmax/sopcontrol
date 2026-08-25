"""sopctl 命令行入口：解析器与 main。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .cli_common import *
from .cli_core import *
from .cli_task import *
from .cli_intent import *
from .cli_identity import *
from .cli_harness import *
from .cli_rules import *
from .registry import RegistryError
from .repair import RepairError

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sopctl",
        description="SOP Control 行走骨架：规则—证据—判定控制平面（观察模式）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="在目标项目初始化 .sopcontrol/")
    p.add_argument("path", nargs="?", default=".", help="目标项目路径，默认当前目录")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("graph", help="Python 文件级 import 邻接图（项目认知薄卡）")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--limit", type=int, default=50, help="最多列出多少个文件")
    p.set_defaults(func=cmd_graph)

    rule = sub.add_parser("rule", help="规则登记与生命周期")
    rule_sub = rule.add_subparsers(dest="sub", required=True)

    p = rule_sub.add_parser("add", help="登记一条规则")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--id", required=True, help="规则 id，如 PUSH-001")
    p.add_argument("--statement", required=True, help="规则陈述")
    p.add_argument("--modality", default="MUST", choices=[m.value for m in Modality])
    p.add_argument("--status", default="proposed", choices=[s.value for s in RuleStatus])
    p.add_argument("--scope", default="project")
    p.add_argument("--owner", default="user")
    p.add_argument("--risk", default="medium", choices=[r.value for r in RiskLevel])
    p.add_argument("--source-type", default="document", help="user_conversation/document/corpus/constitution/manual_seed")
    p.add_argument("--source-ref", required=True, help="出处，如 docs/sop.md 或对话引用")
    p.add_argument("--consumer-marker", action="append", help="什么符号/入口算生产消费者，可重复")
    p.add_argument("--tag", action="append")
    p.set_defaults(func=cmd_rule_add)

    p = rule_sub.add_parser("list", help="列出规则")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_rule_list)

    p = rule_sub.add_parser("accept", help="接受一条规则（生命周期迁移）")
    p.add_argument("rule_id")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_rule_accept)

    p = sub.add_parser("audit", help="运行传感器→检测器→判定，产出吸收矩阵")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--strict", action="store_true", help="存在 gap/fail 时退出码 1（CI 门）")
    p.add_argument("--json", action="store_true", help="输出 JSON 报告")
    p.add_argument(
        "--compact", action="store_true",
        help="用本轮证据整轮替换账本，清除 stale 噪音（役用清理）",
    )
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("doctor", help="安装自诊：注册表、账本完整性、插件可用性、终态门状态")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument(
        "--vertical", action="store_true",
        help="垂直役用标准：身份与 pre-push 未武装则失败",
    )
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser(
        "vertical-check",
        help="垂直骨干役用闭环：武装身份/投影/钩子 → doctor --vertical → audit/gate/self-test",
    )
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_vertical_check)

    p = sub.add_parser("gate", help="终点门：fail 判定/账本篡改阻断，gap 仅告警（供 hook/CI 调用）")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_gate)

    hook = sub.add_parser("hook", help="git 终态门钩子")
    hook_sub = hook.add_subparsers(dest="sub", required=True)
    p = hook_sub.add_parser("install", help="安装 pre-push 终态门")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--hook", default="pre-push", choices=["pre-push", "pre-commit"])
    p.set_defaults(func=cmd_hook)

    p = sub.add_parser("self-test", help="穿透演习：通过真实命令路径验证 gate 真实阻断已知违规")
    p.set_defaults(func=cmd_self_test)

    task = sub.add_parser("task", help="任务状态机：契约 → 受控执行 → 完成门 → 交付")
    task_sub = task.add_subparsers(dest="sub", required=True)
    p = task_sub.add_parser("open", help="创建任务契约（contract_proposed）")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--objective", required=True, help="任务目标")
    p.add_argument("--allow", action="append", required=True, help="允许写入的路径前缀，可重复")
    p.add_argument("--require-rule", action="append", help="完成定义：这些规则必须全部判定 pass")
    p.add_argument(
        "--require-field", action="append",
        help="MUST 输出字段名（可重复；弱模型画像下 accept 强制要求）",
    )
    p.add_argument(
        "--max-repairs", type=int, default=None,
        help="修复预算（默认跟模型画像；无画像时 2 轮；显式传参优先于画像）",
    )
    p.set_defaults(func=cmd_task)
    def _task_cmd(name: str, help_text: str, *, task_id: bool = False, changed: bool = False, fields: bool = False):
        p = task_sub.add_parser(name, help=help_text)
        if task_id:
            p.add_argument("task_id")
        if changed:
            p.add_argument("--changed", action="append", help="本次改动路径，可重复")
        if fields:
            p.add_argument("--field", action="append", help="提交时的 MUST 字段 key=value，可重复")
        p.add_argument("path", nargs="?", default=".")
        p.set_defaults(func=cmd_task)

    _task_cmd("accept", "接受契约 → executing", task_id=True)
    _task_cmd(
        "submit", "提交改动路径 → verification_pending（范围检查 + MUST 字段）",
        task_id=True, changed=True, fields=True,
    )
    _task_cmd("verify", "完成门：独立审计 → verified/repair/blocked/failed", task_id=True)
    _task_cmd("deliver", "交付（仅 verified 可交付）", task_id=True)
    _task_cmd("show", "查看任务状态与 envelope 历史", task_id=True)
    _task_cmd("takeover", "接管包：新模型/新会话的最小接手信息（只读）", task_id=True)
    _task_cmd("list", "列出任务")

    identity = sub.add_parser("identity", help="项目身份（Phase 6 种子：跨 harness 识别同一项目）")
    identity_sub = identity.add_subparsers(dest="sub", required=True)
    for name, help_text in (
        ("init", "创建或刷新 .sopcontrol/identity.yaml"),
        ("show", "显示项目身份"),
        ("lock", "锁定 project_id：挪目录不重算（缓解 R11）"),
        ("unlock", "解锁：恢复按绝对路径派生"),
    ):
        p = identity_sub.add_parser(name, help=help_text)
        p.add_argument("path", nargs="?", default=".")
        p.set_defaults(func=cmd_identity)
    p = identity_sub.add_parser("export", help="导出可携带身份包（默认锁定）")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--out", help="写入文件（默认 stdout）")
    p.set_defaults(func=cmd_identity)
    p = identity_sub.add_parser("import", help="导入身份包并锁定到当前项目")
    p.add_argument("--file", required=True, help="export 产出的 YAML")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_identity)

    p = sub.add_parser(
        "intake",
        help="意图编译器 v0：文档 MUST 句和/或对话摘录 → Candidate（observed，不写终态）",
    )
    p.add_argument("path", nargs="?", default=".")
    p.add_argument(
        "--conversation",
        help="对话摘录文件：识别 discuss_only / 永久政策候选（14.1 场景1）",
    )
    p.add_argument(
        "--with-docs", action="store_true",
        help="处理对话时同时扫描文档 MUST 句（默认对话路径单独运行）",
    )
    p.set_defaults(func=cmd_intake)

    intent = sub.add_parser("intent", help="会话意图：查看/清除 discuss_only 锁定")
    intent_sub = intent.add_subparsers(dest="sub", required=True)
    p = intent_sub.add_parser("show", help="显示当前会话意图")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_intent)
    p = intent_sub.add_parser("clear", help="清除 discuss_only 锁定")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_intent)

    repair = sub.add_parser("repair", help="有界修复：Finding → 修复任务（同指纹熔断）")
    repair_sub = repair.add_subparsers(dest="sub", required=True)
    p = repair_sub.add_parser("open", help="为某条 finding 开修复任务")
    p.add_argument("finding_id")
    p.add_argument("--allow", action="append", required=True, help="允许修复改动的路径前缀，可重复")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_repair)
    p = repair_sub.add_parser("list", help="列出修复任务")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_repair)

    p = sub.add_parser("harness-check", help="harness 工具调用决策（stdin/--payload JSON → stdout 决策；供 hook/plugin 调用）")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--payload", help="工具调用 JSON（默认读 stdin）")
    p.set_defaults(func=cmd_harness_check)

    p = hook_sub.add_parser("claude", help="安装 Claude Code PreToolUse 钩子（项目级 settings.json，合并式）")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_hook_claude)

    p = hook_sub.add_parser("opencode", help="安装 OpenCode 运行时插件（.opencode/plugins，工具调用前拦截）")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_hook_opencode)

    project = sub.add_parser("project", help="平台规则投影（建议层，权威源仍是 registry）")
    project_sub = project.add_subparsers(dest="sub", required=True)
    for name, help_text in (
        ("codex", "AGENTS.md（Codex；无运行时钩子，靠终态门兜底）"),
        ("opencode", "AGENTS.md（OpenCode 优先读此文件）"),
        ("claude", "CLAUDE.md（Claude Code 项目指导）"),
        ("all", "同步 AGENTS.md + CLAUDE.md（Rulesync 式）"),
        ("check", "检测投影是否相对 registry 过期（漂移则退出码 1）"),
    ):
        p = project_sub.add_parser(name, help=help_text)
        p.add_argument("path", nargs="?", default=".")
        p.set_defaults(func=cmd_project)

    p = sub.add_parser("wrap", help="事后门 wrapper：运行 harness 命令后执行终点门")
    p.add_argument("harness", choices=["codex"])
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_wrap)

    p = sub.add_parser("harness-profile", help="写入 harness 能力画像（.sopcontrol/harness-profile.yaml）")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_harness_profile)

    p = sub.add_parser("harness-eval", help="对真实 harness 执行穿透演习并记录画像（消耗模型 token）")
    p.add_argument("harness", choices=["opencode", "codex", "scenario7"])
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_harness_eval)

    p = sub.add_parser(
        "capability-eval",
        help="模型能力握手：三维探针打分 → model-profile.yaml（夹具不烧 token；调节 task open 旋钮）",
    )
    p.add_argument("--model", required=True, help="模型标识（写入画像，如 ox-alpha-free）")
    p.add_argument(
        "--fixture", choices=["strong", "fragile", "weak"],
        help="离线夹具：不烧 token 即可走通握手闭环",
    )
    p.add_argument(
        "--responses",
        help="YAML 文件：三探针响应 {json_stability, boundary_follow, instruction_follow}",
    )
    p.add_argument(
        "--live", choices=["opencode"],
        help="真实 harness 探针（烧 token；结果如实归档，超时/失败不算通过）",
    )
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_capability_eval)

    p = sub.add_parser(
        "capability-compare",
        help="live 探针 vs 夹具基线对比 → capability-compare.yaml",
    )
    p.add_argument("--model", default="opencode-default", help="live 侧模型标识")
    p.add_argument("--live", choices=["opencode"], default="opencode")
    p.add_argument("--no-live", action="store_true", help="只跑多夹具基线，不烧 token")
    p.add_argument("--baselines-all", action="store_true", help="归档 strong/fragile/weak 三基线")
    p.add_argument(
        "--baseline", choices=["strong", "fragile", "weak"], default="strong",
        help="对比用的离线夹具基线",
    )
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_capability_compare)

    p = sub.add_parser("explain", help="解释某条规则的判定：谁消费、证据是什么、为什么")
    p.add_argument("rule_id")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_explain)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (RegistryError, RepairError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2


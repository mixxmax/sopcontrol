"""CLI commands — cli_harness.py."""
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



def cmd_capability_compare(args) -> int:
    """live 探针 vs 夹具基线对比，追加 capability-compare.yaml。"""
    from .evals import run_capability_compare

    root = _project(args.path)
    baselines_all = bool(getattr(args, "baselines_all", False))
    live = None if getattr(args, "no_live", False) else args.live
    if baselines_all or live is None:
        print(f"多基线对比 baselines_all={baselines_all} live={live}…")
    else:
        print(f"对比 live={live} vs baseline={args.baseline}（live 耗 token）…")
    try:
        result = run_capability_compare(
            root,
            live=live,
            baseline_fixture=args.baseline,
            live_model=args.model,
            baselines_all=baselines_all or live is None,
        )
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    entry = result["entry"]
    print(f"已追加 → {result['compare_path']}")
    if entry.get("kind") == "multi-baseline":
        for b in entry.get("baselines") or []:
            print(f"  baseline {b['source']}: tier={b['tier']}")
        if entry.get("live"):
            print(f"  live: tier={entry['live']['tier']} scores={entry['live']['scores']}")
    else:
        print(f"  live:     tier={entry['live']['tier']}  scores={entry['live']['scores']}")
        print(
            f"  baseline: tier={entry['baseline']['tier']}  "
            f"scores={entry['baseline']['scores']}"
        )
        print(f"  tier_match: {entry['tier_match']}")
    return 0



def cmd_capability_eval(args) -> int:
    """模型维度握手：夹具/响应文件/live harness → tier → model-profile.yaml。"""
    from .evals import run_capability_eval

    root = _project(args.path)
    responses = None
    if args.responses:
        data = yaml.safe_load(Path(args.responses).read_text(encoding="utf-8")) or {}
        responses = {str(k): str(v) for k, v in data.items()}
    if getattr(args, "live", None):
        print(f"对 {args.live} 执行三维能力探针（消耗模型 token）…")
    try:
        result = run_capability_eval(
            root, args.model,
            fixture=args.fixture,
            responses=responses,
            live=getattr(args, "live", None),
        )
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    print(f"模型画像已写入 → {result['profile_path']}")
    print(f"  model={result['model']}  tier={result['tier']}  source={result['source']}")
    for probe, ok in result["scores"].items():
        print(f"  {probe}: {'通过' if ok else '失败'}")
    knobs = result["knobs"]
    print(
        f"  旋钮: max_repairs={knobs['max_repairs']}  "
        f"write_granularity={knobs['write_granularity']}"
        f"  strict_schema={knobs.get('strict_schema')}"
    )
    print(f"  理由: {knobs['reason']}")
    return 0



def cmd_harness_check(args) -> int:
    """harness 工具调用决策：stdin JSON 或 --payload；stdout 出决策 JSON。"""
    from .harness import check_tool_call, gate_status_for_push
    from .intent import load_session_intent

    root = _project(args.path)
    raw = args.payload if args.payload else (sys.stdin.read() or "{}")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        decision = HookDecision(
            permissionDecision="deny",
            reason=f"harness check 无法解析输入（{exc}）：解析失败 fail-closed",
        )
    else:
        gate_status = None
        command = str((payload.get("tool_input") or {}).get("command") or "")
        if PUSH_RE.search(command):
            gate_status = gate_status_for_push(root)
        session = load_session_intent(root)
        decision = check_tool_call(payload, gate_status, session_intent=session.intent)

    print(json.dumps(decision.claude_payload(), ensure_ascii=False))
    return 0



def cmd_harness_eval(args) -> int:
    """能力评测：一次性沙箱内对真实 harness 执行挑衅剧本（会消耗模型 token）。"""
    from .evals import run_harness_eval

    root = _project(args.path)
    profile_path = root / ".sopcontrol" / "harness-profile.yaml"
    if not profile_path.exists():
        _write_profile(root)
    print(f"对 {args.harness} 执行穿透演习（一次性沙箱，消耗该 harness 的模型 token）…")
    results = run_harness_eval(args.harness, profile_path)
    ok = True
    for r in results:
        print(f"{'通过' if r['passed'] else '失败'}: {r['drill']}（exit={r['exit_code']}）")
        print(f"  证据: {r['evidence'][:120]}")
        ok = ok and r["passed"]
    print(f"结果已追加 → {profile_path}")
    return 0 if ok else 1



def cmd_harness_profile(args) -> int:
    root = _project(args.path)
    _write_profile(root)
    path = root / ".sopcontrol" / "harness-profile.yaml"
    print(f"已写入能力画像 → {path}")
    for name, profile in yaml.safe_load(path.read_text(encoding="utf-8")).items():
        print(f"  {name}: 拦截={profile.get('interception')}")
    return 0



def cmd_hook_claude(args) -> int:
    """把 sopctl harness check 装进项目 .claude/settings.json 的 PreToolUse（合并，不覆盖他人配置）。"""
    root = _project(args.path)
    settings_path = root / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    data = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"错误: {settings_path} 不是合法 JSON，拒绝合并（请手工整合）", file=sys.stderr)
            return 2

    command = f'"{sys.executable}" -m sopcontrol.cli harness check'
    pre = data.setdefault("hooks", {}).setdefault("PreToolUse", [])
    entry = {"matcher": "Bash|Write|Edit|MultiEdit", "hooks": [{"type": "command", "command": command}]}

    replaced = False
    for existing in pre:
        for h in existing.get("hooks", []):
            if "sopcontrol.cli" in str(h.get("command", "")):
                h["command"] = command
                existing["matcher"] = entry["matcher"]
                replaced = True
    if not replaced:
        pre.append(entry)

    settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已安装 Claude Code PreToolUse 钩子 → {settings_path}")
    print("生效方式: 在该目录运行 claude，工具调用将经过 sopctl 决策（deny/ask/allow）")
    return 0



def cmd_hook_opencode(args) -> int:
    """安装 OpenCode 运行时插件（.opencode/plugins/sopcontrol.js，工具调用前拦截）。"""
    root = _project(args.path)
    plugin_path = root / ".opencode" / "plugins" / "sopcontrol.js"
    if plugin_path.exists() and "sopcontrol-hook v1" not in plugin_path.read_text(encoding="utf-8"):
        print(f"拒绝覆盖: {plugin_path} 已存在且非 sopctl 安装", file=sys.stderr)
        return 2
    plugin_path.parent.mkdir(parents=True, exist_ok=True)
    plugin_path.write_text(
        OPENCODE_PLUGIN_TEMPLATE.format(
            python_json=json.dumps(sys.executable),
            project_json=json.dumps(str(root)),
        ),
        encoding="utf-8",
    )
    _write_profile(root)
    print(f"已安装 OpenCode 运行时插件 → {plugin_path}")
    print("拦截点: tool.execute.before（bash/edit/write）；deny/ask 均抛错阻断，决策来自 sopctl")
    return 0



def cmd_project(args) -> int:
    """平台规则投影：codex/opencode → AGENTS.md；claude → CLAUDE.md；all → 两者。"""
    from .project import write_all_projections, write_projection

    root = _project(args.path)
    sub = args.sub
    try:
        if sub == "all":
            paths = write_all_projections(root)
        else:
            paths = [write_projection(root, sub)]
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    _write_profile(root)
    for p in paths:
        print(f"已写入规则投影 → {p}（只替换带标记小节；权威源仍是 registry.yaml）")
    if sub == "codex":
        print("Codex 控制策略: 建议（本投影）+ 事后门（sopctl wrap codex）+ git/CI 终态拦截")
    elif sub == "opencode":
        print("OpenCode 控制策略: 建议（本投影）+ 运行时插件（sopctl hook opencode）+ git/CI")
    elif sub == "claude":
        print("Claude 控制策略: 建议（本投影）+ PreToolUse 钩子（sopctl hook claude）+ git/CI")
    else:
        print("已同步 AGENTS.md 与 CLAUDE.md；各 harness 控制策略不变")
    return 0



def cmd_rule_accept(args) -> int:
    root = _project(args.path)
    rule = Registry(root / ".sopcontrol" / "rules" / "registry.yaml").transition(
        args.rule_id, RuleStatus.accepted
    )
    print(f"{rule.rule_id} 已接受（accepted_at={rule.accepted_at}）；下一步 sopctl audit 检查吸收")
    return 0



def cmd_rule_add(args) -> int:
    from .conflict import find_conflicts

    root = _project(args.path)
    reg = Registry(root / ".sopcontrol" / "rules" / "registry.yaml")
    rule = Rule(
        rule_id=args.id,
        statement=args.statement,
        modality=Modality(args.modality),
        status=RuleStatus(args.status),
        scope=args.scope,
        owner=args.owner,
        risk=RiskLevel(args.risk),
        source=SourceRef(type=args.source_type, ref=args.source_ref),
        consumer_markers=list(args.consumer_marker or []),
        tags=list(args.tag or []),
    )
    if rule.status == RuleStatus.accepted:
        conflicts = find_conflicts(rule, reg.load())
        if conflicts:
            detail = "；".join(c["reason"] for c in conflicts)
            print(f"错误: 规则冲突（14.1 场景10）：{detail}", file=sys.stderr)
            return 2
    reg.add(rule)
    print(f"已登记规则 {rule.rule_id} [{rule.status.value}]：{rule.statement}")
    if rule.status == RuleStatus.accepted:
        print("注意：规则已直接置为 accepted；常规流程应从 proposed 出发，经确认后 accept")
    return 0



def cmd_rule_list(args) -> int:
    root = _project(args.path)
    rules = Registry(root / ".sopcontrol" / "rules" / "registry.yaml").load()
    if not rules:
        print("注册表为空")
        return 0
    print(f"{'RULE':16} {'状态':10} {'强度':9} {'吸收标记':24} 陈述")
    for r in rules:
        markers = ",".join(r.consumer_markers) or "-"
        print(f"{r.rule_id:16} {r.status.value:10} {r.modality.value:9} {markers:24} {r.statement[:40]}")
    return 0



def cmd_wrap(args) -> int:
    """事后门 wrapper：运行 harness 命令，结束后跑终点门；门失败则退出码非零。"""
    import subprocess

    root = _project(args.path)
    rest = list(args.rest or [])
    if rest and rest[0] == "--":
        rest = rest[1:]
    if not rest:
        print("用法: sopctl wrap codex [PATH] -- <codex 参数...>", file=sys.stderr)
        return 2
    if args.harness != "codex":
        print(f"wrap 暂只支持 codex（{args.harness} 有实时拦截，无需 wrap）", file=sys.stderr)
        return 2
    proc = subprocess.call(["codex"] + rest, cwd=str(root))
    print(f"\n[sopctl wrap] codex 退出码 {proc}；运行事后终点门…")
    gate_code = run_gate(root)
    if gate_code != 0:
        print("[sopctl wrap] 事后门未过：变更未获信任，git 推送将被 pre-push 钩子与 CI 阻断", file=sys.stderr)
    return proc if proc != 0 else gate_code


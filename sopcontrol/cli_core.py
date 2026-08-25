"""CLI commands — cli_core.py."""
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



def cmd_audit(args) -> int:
    from plugins import DETECTORS, SENSORS

    root = _project(args.path)
    compact = bool(getattr(args, "compact", False))
    report = run_audit(root, SENSORS, DETECTORS, persist=True, compact=compact)

    if args.json:
        print(json.dumps({
            "rules": [r.model_dump(mode="json") for r in report.rules],
            "evidence_count": len(report.evidence),
            "findings": [f.model_dump(mode="json") for f in report.findings],
            "verdicts": [v.model_dump(mode="json") for v in report.verdicts],
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"{'RULE':16} {'判定':8} {'吸收':18} 理由")
    for v in report.verdicts:
        absorption = v.absorption.value if v.absorption else "-"
        print(f"{v.rule_id:16} {v.status:8} {absorption:18} {v.reason[:60]}")
    gaps = sum(1 for v in report.verdicts if v.status in ("gap", "fail"))
    n_findings = len(report.findings)
    print(f"\n证据 {len(report.evidence)} 条，finding {n_findings} 条，判定 gap/fail {gaps} 项。")
    ledger = root / ".sopcontrol" / "evidence" / "ledger.jsonl"
    mode = "compact 快照已替换账本" if compact else "观察模式追加账本"
    print(f"账本: {ledger}（{mode}；--strict 可作为 CI 门）")
    if args.strict and gaps:
        return 1
    return 0



def cmd_doctor(args) -> int:
    """安装自诊（CC Safety Net doctor 同款）：注册表可载入、账本未被篡改、插件可用。"""
    root = _project(args.path)
    problems = []

    registry_path = root / ".sopcontrol" / "rules" / "registry.yaml"
    try:
        rules = Registry(registry_path).load()
        print(f"注册表: OK（{len(rules)} 条规则）")
    except RegistryError as exc:
        problems.append(f"注册表: {exc}")

    ledger = Ledger(root / ".sopcontrol" / "evidence" / "ledger.jsonl")
    if ledger.path.exists():
        ok = ledger.verify()
        print(f"账本完整性: {'OK' if ok else '被篡改或损坏'}")
        if not ok:
            problems.append("账本校验失败：存在 id 与内容不符的记录")
        from .stale import partition_evidence

        _, stale = partition_evidence(root, ledger.load_evidence(current_only=False))
        if stale:
            print(f"账本 stale: {len(stale)} 条（输入已变或过期；explain/判定会忽略，请重新 audit）")
        else:
            print("账本 stale: 无")
    else:
        print("账本: 尚无（audit 后生成）")

    try:
        from plugins import DETECTORS, SENSORS

        print(f"插件: OK（sensors={[s.sensor_id for s in SENSORS]}, detectors={[d.detector_id for d in DETECTORS]}）")
    except Exception as exc:  # 插件加载失败必须暴露，不允许静默降级
        problems.append(f"插件加载失败: {exc}")

    from .identity import load_identity

    ident = load_identity(root)
    if ident:
        print(f"项目身份: {ident.project_id}")
    else:
        print("项目身份: 未登记（sopctl identity init）")
        if getattr(args, "vertical", False):
            problems.append("垂直役用要求已登记项目身份（sopctl identity init）")

    hook = root / ".git" / "hooks" / "pre-push"
    if hook.exists():
        armed = HOOK_MARKER in hook.read_text(encoding="utf-8")
        state = "已武装（sopctl gate）" if armed else "存在但非 sopctl 安装（手工整合请调用 sopctl gate）"
        if getattr(args, "vertical", False) and not armed:
            problems.append("垂直役用要求 pre-push 为 sopctl 终态门")
    else:
        state = "未安装（sopctl hook install）"
        if getattr(args, "vertical", False):
            problems.append("垂直役用要求已安装 pre-push 终态门（sopctl hook install）")
    print(f"pre-push 终态门: {state}")

    if problems:
        for p in problems:
            print(f"问题: {p}", file=sys.stderr)
        return 1
    print("doctor: 全部通过" + ("（垂直役用就绪）" if getattr(args, "vertical", False) else ""))
    return 0



def cmd_explain(args) -> int:
    from .stale import partition_evidence

    root = _project(args.path)
    registry = Registry(root / ".sopcontrol" / "rules" / "registry.yaml")
    rule = registry.get(args.rule_id)
    ledger = Ledger(root / ".sopcontrol" / "evidence" / "ledger.jsonl")
    all_evidence = ledger.load_evidence(current_only=False)
    evidence, stale = partition_evidence(root, all_evidence)
    findings = ledger.load_findings()
    if not evidence and not findings and not stale:
        print("账本为空，判定缺少独立证据；先运行 sopctl audit")
        return 1
    if stale:
        print(f"注意: {len(stale)} 条账本证据因输入变化或过期已 stale，不参与判定（14.1 场景14）")
    verdict = evaluate_rule(rule, evidence, findings)

    print(f"规则 {rule.rule_id} — {rule.statement}")
    print(f"  治理: {rule.status.value}  强度: {rule.modality.value}  范围: {rule.scope}  风险: {rule.risk.value}")
    print(f"  来源: {rule.source.type} → {rule.source.ref}")
    if rule.accepted_at:
        print(f"  接受时间: {rule.accepted_at}")
    print(f"  判定: {verdict.status.upper()}  吸收等级: {verdict.absorption.value if verdict.absorption else '未判定'}")
    print(f"  理由: {verdict.reason}")
    print(f"  下一步: {verdict.next_action}")
    if verdict.evidence_ids:
        print(f"  依据证据: {', '.join(verdict.evidence_ids)}")
    related = [f for f in findings if f.rule_id == rule.rule_id]
    for f in related:
        print(f"  Finding [{f.severity}] {f.pattern_id}: {f.summary}")
    doc_ev = [e for e in evidence if e.kind == "doc_scan.must_statement" and rule.source.ref == e.subject]
    for e in doc_ev[:3]:
        print(f"  文档声明证据 {e.evidence_id}: {str(e.observed)[:60]}")
    return 0



def cmd_gate(args) -> int:
    return run_gate(_project(args.path))



def cmd_hook(args) -> int:
    root = _project(args.path)
    git_dir = root / ".git"
    if not git_dir.exists():
        print(f"错误: {root} 不是 git 仓库", file=sys.stderr)
        return 2
    hook_path = git_dir / "hooks" / args.hook
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    if hook_path.exists() and HOOK_MARKER not in hook_path.read_text():
        print(
            f"拒绝覆盖: {hook_path} 已存在且不是 sopctl 安装的钩子；"
            f"如需整合，请在你自己的钩子里调用 sopctl gate",
            file=sys.stderr,
        )
        return 2
    hook_path.write_text(HOOK_TEMPLATE, encoding="utf-8")
    hook_path.chmod(0o755)
    print(f"已安装 {args.hook} 终态门: {hook_path}")
    return 0



def cmd_init(args) -> int:
    from .identity import ensure_identity

    root = _project(args.path)
    sc = root / ".sopcontrol"
    if sc.exists():
        print(f"已初始化，跳过: {sc}")
        return 0
    (sc / "rules").mkdir(parents=True)
    (sc / "evidence").mkdir(parents=True)
    registry = sc / "rules" / "registry.yaml"
    registry.write_text("rules: []\n", encoding="utf-8")
    (sc / "manifest.yaml").write_text(
        "# controller_paths：本仓库中构成控制器/验证器自身的路径前缀。\n"
        "# 列出的路径在本项目任务里被改动时，必须先提交基线才能通过完成门（手册 9.3）。\n"
        "controller_paths: []\n",
        encoding="utf-8",
    )
    ident = ensure_identity(root)
    print(f"已在 {root} 初始化 .sopcontrol/（规则注册表 + 证据账本 + manifest + 身份）")
    print(f"  project_id: {ident.project_id}")
    print("下一步: sopctl rule add 登记规则，然后 sopctl audit")
    return 0



def cmd_self_test(args) -> int:
    """穿透演习（消防演习语义）：通过真实命令路径注入已知违规，断言被真实阻断。"""
    import shutil
    import tempfile

    canary_rule = """rules:
- rule_id: SHIP-001
  statement: 发货必须经 ship_gate 受控入口，遗留直发脚本不得存活
  modality: MUST
  status: accepted
  scope: shipping
  owner: product
  risk: high
  source:
    type: document
    ref: docs/sop.md
  consumer_markers:
  - ship_gate
  legacy_markers:
  - legacy_ship
"""
    legacy_alive = "def legacy_ship(pkg):\n    return {'sent': pkg}\n"
    legacy_gone = "# 旧直发入口已下线\n"

    with tempfile.TemporaryDirectory() as tmp:
        canary = Path(tmp) / "canary"
        (canary / "docs").mkdir(parents=True)
        (canary / "src").mkdir()
        (canary / "tests").mkdir()
        (canary / ".sopcontrol" / "rules").mkdir(parents=True)
        (canary / "docs" / "sop.md").write_text("# 发货 SOP\n- 发货必须经 ship_gate 受控入口。\n")
        (canary / "src" / "ship.py").write_text("def ship_gate(pkg):\n    return {'sent': pkg, 'gated': True}\n")
        (canary / "tests" / "test_ship.py").write_text(
            "from ship import ship_gate\n\ndef test_gated():\n    assert ship_gate('p')['gated']\n"
        )
        (canary / ".sopcontrol" / "rules" / "registry.yaml").write_text(canary_rule)

        results = []

        # 演习1：旧入口存活 → gate 必须阻断
        (canary / "src" / "legacy.py").write_text(legacy_alive)
        from sopcontrol.cli import main as _main

        results.append(("旧入口存活被阻断", _main(["gate", str(canary)]) == 1))

        # 演习2：清洁现场 → gate 必须放行（防"永远报警"）
        (canary / "src" / "legacy.py").write_text(legacy_gone)
        ledger_path = canary / ".sopcontrol" / "evidence" / "ledger.jsonl"
        ledger_path.unlink(missing_ok=True)
        results.append(("清洁现场被放行", _main(["gate", str(canary)]) == 0))

        # 演习3：现场清洁、仅账本被篡改 → gate 仍必须阻断（信任根）
        ledger_path.write_text(
            '{"evidence_id": "ev-fake", "kind": "code_scan.identifiers", "subject": "src/x.py",'
            ' "observed": ["x"], "observer": "code_scan", "input_hash": "deadbeef"}\n'
        )
        results.append(("账本篡改被阻断", _main(["gate", str(canary)]) == 1))

    ok = True
    for name, passed in results:
        print(f"{'通过' if passed else '失败'}: {name}")
        ok = ok and passed
    if not ok:
        print("self-test: 存在演习失败——终态门不可信，按 fail-closed 处理", file=sys.stderr)
    return 0 if ok else 1



def cmd_vertical_check(args) -> int:
    """垂直骨干役用：武装身份/投影/钩子 → doctor --vertical → audit/gate/self-test。"""
    from .identity import ensure_identity
    from .project import write_all_projections

    root = _project(args.path)
    if not (root / ".sopcontrol").exists():
        print("错误: 尚未 sopctl init", file=sys.stderr)
        return 2

    ident = ensure_identity(root)
    print(f"身份: OK → {ident.project_id}")
    for p in write_all_projections(root):
        print(f"投影: OK → {p}")

    from .evals import run_capability_eval

    try:
        cap = run_capability_eval(root, "vertical-backbone", fixture="strong")
        print(f"能力画像: OK → tier={cap['tier']}")
    except Exception as exc:
        print(f"能力画像: 跳过（{exc}）")

    # 复用 hook install（无 git 则失败）
    class _HookArgs:
        path = str(root)
        hook = "pre-push"

    hook_code = cmd_hook(_HookArgs())
    if hook_code != 0:
        return hook_code

    class _DocArgs:
        path = str(root)
        vertical = True

    if cmd_doctor(_DocArgs()) != 0:
        return 1

    from plugins import DETECTORS, SENSORS

    report = run_audit(root, SENSORS, DETECTORS, persist=True, compact=True)
    fails = [v for v in report.verdicts if v.status == "fail"]
    gaps = [v for v in report.verdicts if v.status == "gap"]
    print(f"audit: fail={len(fails)} gap={len(gaps)}（账本已 compact）")
    if fails:
        for v in fails:
            print(f"  FAIL {v.rule_id}: {v.reason[:100]}", file=sys.stderr)
        print("vertical-check: 存在 fail 判定，骨干役用未闭环", file=sys.stderr)
        return 1

    if run_gate(root) != 0:
        return 1

    # self-test 在一次性沙箱，不碰本仓
    class _ST:
        pass

    if cmd_self_test(_ST()) != 0:
        return 1

    print("vertical-check: 通过——垂直骨干役用闭环（日用见 PLAYBOOK.md）")
    return 0


def cmd_graph(args) -> int:
    """打印 Python 文件级 import 邻接（import_graph 薄卡）。"""
    from plugins.sensors.import_graph import ImportGraphSensor, build_adjacency

    root = _project(args.path)
    evidence = ImportGraphSensor().observe(
        __import__("sopcontrol.context", fromlist=["ProjectContext"]).ProjectContext(root)
    )
    adj = build_adjacency(evidence)
    if not adj:
        print("无 import 边（或无可解析 .py）")
        return 0
    limit = int(getattr(args, "limit", 50) or 50)
    for i, (subj, mods) in enumerate(adj.items()):
        if i >= limit:
            print(f"... 另有 {len(adj) - limit} 个文件未列出（--limit 可调）")
            break
        print(f"{subj} → {', '.join(mods)}")
    return 0


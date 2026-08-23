"""sopctl 命令行：init / rule / audit / explain。

audit 默认是观察模式（L0/L1，只建议不阻断，退出码 0）；
--strict 供 CI 终态门使用：存在 gap/fail 即退出码 1（ Haft check 语义）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .audit import run_audit
from .ledger import Ledger
from .model import Modality, RiskLevel, Rule, RuleStatus, SourceRef
from .registry import Registry, RegistryError
from .verdict import evaluate_rule


def _project(path: str) -> Path:
    return Path(path).resolve()


def cmd_init(args) -> int:
    root = _project(args.path)
    sc = root / ".sopcontrol"
    if sc.exists():
        print(f"已初始化，跳过: {sc}")
        return 0
    (sc / "rules").mkdir(parents=True)
    (sc / "evidence").mkdir(parents=True)
    registry = sc / "rules" / "registry.yaml"
    registry.write_text("rules: []\n", encoding="utf-8")
    print(f"已在 {root} 初始化 .sopcontrol/（规则注册表 + 证据账本目录）")
    print("下一步: sopctl rule add 登记规则，然后 sopctl audit")
    return 0


def cmd_rule_add(args) -> int:
    root = _project(args.path)
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
    Registry(root / ".sopcontrol" / "rules" / "registry.yaml").add(rule)
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


def cmd_rule_accept(args) -> int:
    root = _project(args.path)
    rule = Registry(root / ".sopcontrol" / "rules" / "registry.yaml").transition(
        args.rule_id, RuleStatus.accepted
    )
    print(f"{rule.rule_id} 已接受（accepted_at={rule.accepted_at}）；下一步 sopctl audit 检查吸收")
    return 0


def cmd_audit(args) -> int:
    from plugins import DETECTORS, SENSORS

    root = _project(args.path)
    report = run_audit(root, SENSORS, DETECTORS, persist=True)

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
    print(f"账本: {ledger}（观察模式，未阻断任何操作；--strict 可作为 CI 门）")
    if args.strict and gaps:
        return 1
    return 0


def cmd_explain(args) -> int:
    root = _project(args.path)
    registry = Registry(root / ".sopcontrol" / "rules" / "registry.yaml")
    rule = registry.get(args.rule_id)
    ledger = Ledger(root / ".sopcontrol" / "evidence" / "ledger.jsonl")
    evidence = ledger.load_evidence()
    findings = ledger.load_findings()
    if not evidence and not findings:
        print("账本为空，判定缺少独立证据；先运行 sopctl audit")
        return 1
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


HOOK_MARKER = "# sopcontrol-hook v1"
HOOK_TEMPLATE = f"""#!/bin/sh
{HOOK_MARKER}
# 终态门：fail 判定或账本篡改则阻断 push（gap 仅警告）
exec sopctl gate "$(git rev-parse --show-toplevel)"
"""


def cmd_gate(args) -> int:
    """终点执行器：fail 阻断、gap 告警、审计异常 fail-closed。"""
    from plugins import DETECTORS, SENSORS

    root = _project(args.path)
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
        results.append(("旧入口存活被阻断", main(["gate", str(canary)]) == 1))

        # 演习2：清洁现场 → gate 必须放行（防"永远报警"）
        (canary / "src" / "legacy.py").write_text(legacy_gone)
        ledger_path = canary / ".sopcontrol" / "evidence" / "ledger.jsonl"
        ledger_path.unlink(missing_ok=True)
        results.append(("清洁现场被放行", main(["gate", str(canary)]) == 0))

        # 演习3：现场清洁、仅账本被篡改 → gate 仍必须阻断（信任根）
        ledger_path.write_text(
            '{"evidence_id": "ev-fake", "kind": "code_scan.identifiers", "subject": "src/x.py",'
            ' "observed": ["x"], "observer": "code_scan", "input_hash": "deadbeef"}\n'
        )
        results.append(("账本篡改被阻断", main(["gate", str(canary)]) == 1))

    ok = True
    for name, passed in results:
        print(f"{'通过' if passed else '失败'}: {name}")
        ok = ok and passed
    if not ok:
        print("self-test: 存在演习失败——终态门不可信，按 fail-closed 处理", file=sys.stderr)
    return 0 if ok else 1


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
    else:
        print("账本: 尚无（audit 后生成）")

    try:
        from plugins import DETECTORS, SENSORS

        print(f"插件: OK（sensors={[s.sensor_id for s in SENSORS]}, detectors={[d.detector_id for d in DETECTORS]}）")
    except Exception as exc:  # 插件加载失败必须暴露，不允许静默降级
        problems.append(f"插件加载失败: {exc}")

    hook = root / ".git" / "hooks" / "pre-push"
    if hook.exists():
        armed = HOOK_MARKER in hook.read_text()
        state = "已武装（sopctl gate）" if armed else "存在但非 sopctl 安装（手工整合请调用 sopctl gate）"
    else:
        state = "未安装（sopctl hook install）"
    print(f"pre-push 终态门: {state}")

    if problems:
        for p in problems:
            print(f"问题: {p}", file=sys.stderr)
        return 1
    print("doctor: 全部通过")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sopctl",
        description="SOP Control 行走骨架：规则—证据—判定控制平面（观察模式）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="在目标项目初始化 .sopcontrol/")
    p.add_argument("path", nargs="?", default=".", help="目标项目路径，默认当前目录")
    p.set_defaults(func=cmd_init)

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
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("doctor", help="安装自诊：注册表、账本完整性、插件可用性、终态门状态")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_doctor)

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
    except RegistryError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

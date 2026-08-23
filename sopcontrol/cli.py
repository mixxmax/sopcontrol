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

    p = sub.add_parser("doctor", help="安装自诊：注册表、账本完整性、插件可用性")
    p.add_argument("path", nargs="?", default=".")
    p.set_defaults(func=cmd_doctor)

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

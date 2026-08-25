"""sopctl 命令行：init / rule / audit / explain。

audit 默认是观察模式（L0/L1，只建议不阻断，退出码 0）；
--strict 供 CI 终态门使用：存在 gap/fail 即退出码 1（ Haft check 语义）。
"""
from __future__ import annotations

import argparse
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


def _project(path: str) -> Path:
    return Path(path).resolve()


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


def cmd_identity(args) -> int:
    from .identity import (
        ensure_identity,
        export_identity,
        import_identity,
        load_identity,
        set_identity_locked,
    )

    root = _project(args.path)
    if args.sub == "init":
        ident = ensure_identity(root)
        print(f"项目身份 → {ident.project_id}")
        print(f"  root: {ident.root}  locked={ident.locked}")
        return 0
    if args.sub == "show":
        ident = load_identity(root)
        if ident is None:
            print("尚无项目身份；运行 sopctl identity init", file=sys.stderr)
            return 1
        print(yaml.safe_dump(ident.model_dump(mode="json"), allow_unicode=True, sort_keys=False).strip())
        return 0
    if args.sub == "lock":
        ident = set_identity_locked(root, True)
        print(f"已锁定 project_id → {ident.project_id}（挪目录不重算）")
        return 0
    if args.sub == "unlock":
        ident = set_identity_locked(root, False)
        print(f"已解锁 project_id → {ident.project_id}（将随路径派生）")
        return 0
    if args.sub == "export":
        try:
            payload = export_identity(root)
        except FileNotFoundError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return 2
        out = getattr(args, "out", None)
        text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
        if out:
            Path(out).write_text(text, encoding="utf-8")
            print(f"已导出 → {out}")
        else:
            print(text.strip())
        return 0
    if args.sub == "import":
        src = getattr(args, "file", None)
        if not src:
            print("错误: identity import 需要 --file", file=sys.stderr)
            return 2
        data = yaml.safe_load(Path(src).read_text(encoding="utf-8")) or {}
        try:
            ident = import_identity(root, data)
        except ValueError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return 2
        print(f"已导入并锁定 → {ident.project_id}")
        return 0
    return 2


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


HOOK_MARKER = "# sopcontrol-hook v1"
HOOK_TEMPLATE = f"""#!/bin/sh
{HOOK_MARKER}
# 终态门：fail 判定或账本篡改则阻断 push（gap 仅警告）
exec sopctl gate "$(git rev-parse --show-toplevel)"
"""


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


def cmd_task(args) -> int:
    root = _project(args.path)
    store = TaskStore(root)
    sub = args.sub

    if sub == "open":
        from .capability import apply_knobs_to_open, load_profile

        for p in args.allow:
            try:
                normalize_relpath(p)
            except ValueError as exc:
                print(f"错误: {exc}", file=sys.stderr)
                return 2
        profile = load_profile(root)
        explicit = getattr(args, "max_repairs", None) is not None
        repairs, writes, reject, note = apply_knobs_to_open(
            allowed_writes=list(args.allow),
            max_repairs=args.max_repairs if explicit else 2,
            max_repairs_explicit=explicit,
            profile=profile,
        )
        if reject:
            print(f"错误: {reject}", file=sys.stderr)
            return 2
        gran = profile.knobs.write_granularity if profile else None
        strict = bool(profile and profile.knobs.strict_schema)
        fields = list(args.require_field or [])
        task_id = store.next_task_id()
        task = TaskRecord(
            task_id=task_id,
            contract=Contract(
                objective=args.objective,
                allowed_writes=writes,
                required_rules=list(args.require_rule or []),
                required_fields=fields,
                max_repairs=repairs,
                write_granularity=gran,
                strict_schema=strict,
                capability_note=note if profile else None,
            ),
        )
        store.save(task)
        print(f"已创建任务 {task_id} [contract_proposed]：{args.objective}")
        print(f"  写入范围: {', '.join(writes)}")
        print(f"  完成定义: 规则 {', '.join(args.require_rule or [])} 全部判定 pass")
        if fields:
            print(f"  MUST 字段: {', '.join(fields)}")
        elif strict:
            print("  MUST 字段: （strict_schema，accept 前须补 --require-field）")
        print(f"  修复预算: {repairs}" + (f"（画像调节）" if profile and not explicit else ""))
        if profile:
            print(f"  能力: {note}")
        print("  下一步: sopctl task accept " + task_id)
        return 0

    if sub == "list":
        tasks = store.list_all()
        if not tasks:
            print("无任务")
            return 0
        print(f"{'TASK':12} {'状态':22} {'r':3} {'修复':4} 目标")
        for t in tasks:
            print(f"{t.task_id:12} {t.status.value:22} {t.revision:3} {t.repair_count:4} {t.contract.objective[:40]}")
        return 0

    if sub == "show":
        task = store.load(args.task_id)
        c = task.contract
        print(f"任务 {task.task_id} — {c.objective}")
        print(f"  状态: {task.status.value}  revision: r{task.revision}  修复轮数: {task.repair_count}/{c.max_repairs}")
        print(f"  写入范围: {', '.join(c.allowed_writes)}")
        print(f"  完成定义: {', '.join(c.required_rules)} 全部 pass")
        if task.changed_paths:
            print(f"  已提交改动: {', '.join(task.changed_paths)}")
        for env in task.history[-5:]:
            to = env.to_status.value if env.to_status else "（拒绝）"
            print(f"  [{env.at:%m-%d %H:%M}] {env.action}: {env.from_status.value} → {to} — {env.reason[:60]}")
        return 0

    if sub == "takeover":
        from plugins import DETECTORS, SENSORS

        task = store.load(args.task_id)
        report = run_audit(root, SENSORS, DETECTORS, persist=False)  # 接管是只读动作
        verdicts = {v.rule_id: v.status for v in report.verdicts}
        findings = [
            f"{f.pattern_id}({f.severity})" for f in report.findings
            if f.rule_id in task.contract.required_rules
        ]
        pack = takeover_pack(task, verdicts, findings)
        print(yaml.safe_dump(pack, allow_unicode=True, sort_keys=False).strip())
        return 0

    if sub == "accept":
        return _task_decide(root, args.task_id, "accept")
    if sub == "submit":
        try:
            fields = _parse_fields(getattr(args, "field", None))
        except ValueError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return 2
        return _task_decide(
            root, args.task_id, "submit",
            changed_paths=list(args.changed or []),
            provided_fields=fields or None,
        )
    if sub == "verify":
        return _task_decide(root, args.task_id, "verify")
    if sub == "deliver":
        return _task_decide(root, args.task_id, "deliver")
    return 2


NEGATIVE_KEYWORDS = ("不得", "禁止", "must not", "mustn't", "never ")


def _suggest_modality(statement: str) -> str:
    low = statement.lower()
    return "MUST_NOT" if any(k in low for k in NEGATIVE_KEYWORDS) else "MUST"


def cmd_repair(args) -> int:
    from plugins import DETECTORS, SENSORS

    root = _project(args.path)
    if args.sub == "open":
        try:
            task = open_repair(root, args.finding_id, list(args.allow), SENSORS, DETECTORS)
        except RepairError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return 2
        print(f"已开修复任务 {task.task_id} [contract_proposed]：{task.contract.objective[:60]}")
        print(f"  绑定指纹: {task.contract.repairs_fingerprint}")
        print(f"  完成定义: 规则 {', '.join(task.contract.required_rules)} 判定 pass")
        print("  下一步: 在契约范围内完成最小修复 → task accept/submit/verify（预算两轮，同指纹熔断）")
        return 0

    if args.sub == "list":
        repairs = list_repairs(root)
        if not repairs:
            print("无修复任务")
            return 0
        print(f"{'TASK':12} {'状态':22} {'指纹':18} 目标")
        for t in repairs:
            print(f"{t.task_id:12} {t.status.value:22} {t.contract.repairs_fingerprint:18} {t.contract.objective[:40]}")
        return 0
    return 2


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


def _write_profile(root: Path) -> None:
    from .harness import HARNESS_PROFILES

    path = Path(root) / ".sopcontrol" / "harness-profile.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(HARNESS_PROFILES, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


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


def cmd_capability_compare(args) -> int:
    """live 探针 vs 夹具基线对比，追加 capability-compare.yaml。"""
    from .evals import run_capability_compare

    root = _project(args.path)
    print(
        f"对比 live={args.live} vs baseline={args.baseline} "
        f"（live 会消耗模型 token）…"
    )
    try:
        result = run_capability_compare(
            root,
            live=args.live,
            baseline_fixture=args.baseline,
            live_model=args.model,
        )
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    entry = result["entry"]
    print(f"已追加 → {result['compare_path']}")
    print(
        f"  live:     tier={entry['live']['tier']}  scores={entry['live']['scores']}"
    )
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


if __name__ == "__main__":
    sys.exit(main())

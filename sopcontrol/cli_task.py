"""CLI commands — cli_task.py."""
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



def cmd_repair(args) -> int:
    from plugins import DETECTORS, SENSORS

    from .repair import apply_repair

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
        print(
            "  下一步: sopctl repair apply "
            f"{task.task_id}  或人工在契约内修改后 task accept/submit/verify"
        )
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

    if args.sub == "apply":
        try:
            result = apply_repair(
                root,
                args.task_id,
                harness=getattr(args, "harness", "opencode") or "opencode",
                keep_worktree=bool(getattr(args, "keep_worktree", False)),
            )
        except RepairError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return 2
        print(f"自动修复合并回主树：复制 {len(result['copied'])} 个文件")
        for p in result["copied"]:
            print(f"  + {p}")
        if result["rejected_out_of_contract"]:
            print("契约外改动已丢弃（隔离树内）：")
            for p in result["rejected_out_of_contract"]:
                print(f"  × {p}")
        print(f"下一步: sopctl task accept/submit/verify {args.task_id}")
        return 0
    return 2



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
        current_model = getattr(args, "model", None)
        explicit = getattr(args, "max_repairs", None) is not None
        repairs, knobs, note = apply_knobs_to_open(
            max_repairs=args.max_repairs if explicit else 2,
            max_repairs_explicit=explicit,
            profile=profile,
            current_model=current_model,
        )
        writes = list(args.allow)
        if knobs.write_granularity == "file":
            directories = [p for p in writes if (root / p).is_dir()]
            if directories:
                print(
                    "错误: 当前能力策略采用精确路径授权，不能把现有目录作为 file 范围: "
                    + ", ".join(directories),
                    file=sys.stderr,
                )
                return 2
        gran = knobs.write_granularity
        strict = knobs.strict_schema
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
                capability_note=note,
            ),
        )
        store.save(task)
        print(f"已创建任务 {task_id} [contract_proposed]：{args.objective}")
        print(f"  写入范围: {', '.join(writes)}")
        print(f"  完成定义: 规则 {', '.join(args.require_rule or [])} 全部判定 pass")
        if fields:
            print(f"  MUST 字段: {', '.join(fields)}")
        elif strict:
            print("  MUST 字段: （缺失；当前任务无法 accept，请重新 task open 并带 --require-field）")
        print(f"  修复预算: {repairs}（能力等级上限）")
        print(f"  能力: {note}")
        if strict and not fields:
            print("  下一步: 重新 task open，并声明至少一个 --require-field")
        else:
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


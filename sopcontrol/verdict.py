"""纯函数判定器：无 I/O、无 LLM、无隐藏状态（宪法属性，tests/constitution/test_purity.py 挑衅验证）。

判定不信任检测器：吸收等级由判定器从 Evidence 独立推导，Finding 仅被引用。
"""
from __future__ import annotations

from .context import is_production_path, is_test_path
from .model import (
    Absorption,
    Evidence,
    Finding,
    Modality,
    Rule,
    RuleStatus,
    Verdict,
)

GOVERNANCE_ACTIVE = {
    RuleStatus.accepted,
    RuleStatus.compiled,
    RuleStatus.activated,
    RuleStatus.monitored,
}
HARD_MODALITIES = {Modality.MUST, Modality.MUST_NOT}


_STRUCTURED_KINDS = frozenset({
    "ast_scan.references", "js_scan.references",
    "go_scan.references", "rust_scan.references",
})
_STRUCTURED_SUFFIXES = (
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs",
)


def marker_hit(ev: Evidence, markers: list[str]) -> bool:
    """标记命中：.py/AST、JS/TS、Go 用结构化扫描；其余表面用 grep。"""
    if ev.kind in _STRUCTURED_KINDS:
        return any(m in (ev.observed or []) for m in markers)
    if ev.kind == "code_scan.identifiers":
        if ev.subject.endswith(_STRUCTURED_SUFFIXES):
            return False  # 交给专用扫描器，避免注释假阳性
        return any(m in (ev.observed or []) for m in markers)
    return False


def latest_test_run(evidence: list[Evidence]) -> Evidence | None:
    """本轮的 E4 测试运行证据（手册 4.3）；没有就是 None，判定退回 E3 语义。

    判定器不知道测试怎么跑的、也不去跑——它只读这条已铸好的证据，纯函数属性不变。
    """
    runs = [e for e in evidence if e.kind == "test_run.result" and e.level >= 4]
    if not runs:
        return None
    # 同轮多条（例如多套命令）取最保守的：任一失败即视为未通过
    for ev in runs:
        if not (ev.observed or {}).get("passed"):
            return ev
    return runs[0]


def declared_test_command(evidence: list[Evidence]) -> str | None:
    """项目声明的测试命令（E3，由 audit 每轮铸入）；没有就是 None。

    有它才能区分「没声明所以永不产 E4」和「声明了但本轮没跑」——两者的下一步
    完全不同，混起来会对已声明的项目一直劝它去声明。
    """
    for ev in evidence:
        if ev.kind == "test_run.declared":
            cmd = (ev.observed or {}).get("command")
            if cmd:
                return str(cmd)
    return None


def fresh_trace_guards(evidence: list[Evidence]) -> dict[str, dict]:
    """本轮仍新鲜的运行时 trace 里，哪些 guard 真的作出过决策（手册 6.5 条件6）。

    判定器不读日志文件、也不判断新鲜度：过期的 trace 证据在 run_audit 的
    is_expired 过滤里就被丢掉了，能走到这里的就是有效的。纯函数属性不变。
    """
    guards: dict[str, dict] = {}
    for ev in evidence:
        if ev.kind != "harness.trace" or ev.level < 4:
            continue
        for gid, info in ((ev.observed or {}).get("guards") or {}).items():
            if isinstance(info, dict):
                guards[str(gid)] = info
    return guards


def _trace_note(rule: Rule, trace_guards: dict[str, dict]) -> tuple[bool, str, str]:
    """(条件6是否满足, 写进 reason 的说明, 未满足时的下一步)。

    没绑 guard 的规则不算「未通过」——绝大多数规则靠代码接线而非运行时拦截执行，
    强求它们产 trace 会把判定变成噪音。但没绑就永远拿不到 enforced，这是诚实的代价。
    """
    if not rule.guard_ids:
        return False, "规则未绑定运行时 guard，拿不到 trace 证据", "若该规则由拦截器执行，为其声明 guard_ids"
    missing = [g for g in rule.guard_ids if g not in trace_guards]
    if missing:
        return (
            False,
            f"声明的 guard [{', '.join(missing)}] 在本轮 trace 中无决策记录",
            f"确认拦截器已安装并被真实调用（sopctl hook ...），使 {missing[0]} 留下运行时事件",
        )
    parts = [
        f"{g}×{trace_guards[g].get('count', '?')}"
        for g in rule.guard_ids
    ]
    return True, f"运行时 trace 证明 [{', '.join(parts)}] 本轮真实决策（E4，条件6 满足）", ""


def consumer_evidence(rule: Rule, evidence: list[Evidence]) -> tuple[list[Evidence], list[Evidence]]:
    """返回 (生产路径消费者证据, 测试路径消费者证据)。语料/文档不算接线。"""
    prod, test = [], []
    for ev in evidence:
        if not marker_hit(ev, rule.consumer_markers):
            continue
        if is_test_path(ev.subject):
            test.append(ev)
        elif is_production_path(ev.subject):
            prod.append(ev)
        # meta（corpus/docs）：忽略
    return prod, test


def legacy_evidence(rule: Rule, evidence: list[Evidence]) -> list[Evidence]:
    """生产路径上仍然存活的旧入口证据（测试与语料中出现不算绕过）。"""
    if not rule.legacy_markers:
        return []
    hits = []
    for ev in evidence:
        if marker_hit(ev, rule.legacy_markers) and is_production_path(ev.subject):
            hits.append(ev)
    return hits


def evaluate_rule(rule: Rule, evidence: list[Evidence], findings: list[Finding]) -> Verdict:
    related = [f for f in findings if f.rule_id == rule.rule_id]
    fids = [f.finding_id for f in related]

    if rule.status not in GOVERNANCE_ACTIVE:
        return Verdict(
            rule_id=rule.rule_id,
            status="unknown",
            absorption=None,
            reason=f"规则处于 {rule.status.value}，尚未被接受，没有吸收义务",
            next_action=f"运行 sopctl rule accept {rule.rule_id} 接受它，或保持观察",
            finding_ids=fids,
        )

    if rule.modality not in HARD_MODALITIES:
        return Verdict(
            rule_id=rule.rule_id,
            status="unknown",
            absorption=None,
            reason=f"{rule.modality.value} 规则按手册 4.4 不进入硬吸收判定（落点为建议/评分，不阻断）",
            next_action="无需动作",
            finding_ids=fids,
        )

    prod, test = consumer_evidence(rule, evidence)
    base = _absorption_verdict(
        rule, prod, test, fids,
        related_findings=related,
        test_run=latest_test_run(evidence),
        declared_command=declared_test_command(evidence),
        trace_guards=fresh_trace_guards(evidence),
        trace_ids=[e.evidence_id for e in evidence if e.kind == "harness.trace"],
    )

    legacy = legacy_evidence(rule, evidence)
    if legacy:
        legacy_names = ", ".join(rule.legacy_markers)
        return base.model_copy(
            update={
                "status": "fail",
                "reason": f"生产路径仍存在旧入口 [{legacy_names}]，受控入口可被绕过（{base.reason}）",
                "next_action": "关闭旧入口，或将其改为委托受控入口后移出 legacy_markers",
                "evidence_ids": base.evidence_ids + [e.evidence_id for e in legacy],
            }
        )
    return base


def _absorption_verdict(
    rule: Rule,
    prod: list[Evidence],
    test: list[Evidence],
    fids: list[str],
    *,
    related_findings: list[Finding] | None = None,
    test_run: Evidence | None = None,
    declared_command: str | None = None,
    trace_guards: dict[str, dict] | None = None,
    trace_ids: list[str] | None = None,
) -> Verdict:
    if rule.state_markers and not rule.consumer_markers:
        unread = [
            f for f in (related_findings or [])
            if f.pattern_id == "schema_field_unread"
        ]
        if unread:
            fields = ", ".join(rule.state_markers)
            return Verdict(
                rule_id=rule.rule_id,
                status="gap",
                absorption=Absorption.documented,
                reason=(
                    f"状态/schema 字段 [{fields}] 有写入但生产与测试均无读取"
                    f"（schema_field_unread，14.1 场景3）"
                ),
                next_action="为字段增加真实读取消费者，或从 state_markers 移除未使用字段",
                finding_ids=fids,
            )
        return Verdict(
            rule_id=rule.rule_id,
            status="unknown",
            absorption=None,
            reason="状态类规则：吸收等级不适用，由 state_health 模式评估（write_only/parallel/absent）",
            next_action="关注 audit 输出中的 state_health findings",
            finding_ids=fids,
        )

    if not rule.consumer_markers:
        return Verdict(
            rule_id=rule.rule_id,
            status="unknown",
            absorption=None,
            reason="规则未声明 consumer_markers，无法判定吸收；'什么算消费者'由语料逐模式经验回答，不由宏大定义回答",
            next_action=f"为 {rule.rule_id} 声明 consumer_markers（什么符号/入口算生产消费者）",
            finding_ids=fids,
        )

    markers = ", ".join(rule.consumer_markers)

    if not prod:
        hint = "；消费者标记仅见于测试路径，疑似测试 helper 掩盖生产缺口" if test else ""
        return Verdict(
            rule_id=rule.rule_id,
            status="gap",
            absorption=Absorption.documented,
            reason=f"已接受的 {rule.modality.value} 规则在生产路径没有消费者 [{markers}]{hint}",
            next_action=f"为 {rule.rule_id} 接线生产消费者，或将其降级回 proposed",
            finding_ids=fids,
        )

    if not test:
        return Verdict(
            rule_id=rule.rule_id,
            status="gap",
            absorption=Absorption.wired,
            reason=f"生产消费者已接线 [{markers}]，但测试路径没有回归证据",
            next_action=f"为 {rule.rule_id} 补充负向回归测试（例如：无确认直接写表必须被拒绝）",
            evidence_ids=[e.evidence_id for e in prod],
            finding_ids=fids,
        )

    ids = [e.evidence_id for e in prod + test]

    # E4 闸门：测试路径引用了消费者标记只是 E3——证明有人写了名字，没证明它跑得过。
    # 项目声明了 test_command 时，完成门会铸一条 E4 证据；此处按其退出码分流。
    if test_run is not None:
        observed = test_run.observed or {}
        if not observed.get("passed"):
            code = observed.get("exit_code")
            cmd = observed.get("command", "?")
            why = "超时未结束" if observed.get("timed_out") else f"退出码 {code}"
            return Verdict(
                rule_id=rule.rule_id,
                status="gap",
                absorption=Absorption.wired,
                reason=(
                    f"消费者与测试引用齐备 [{markers}]，但本轮测试命令未通过"
                    f"（{cmd} → {why}）：回归证据不成立"
                ),
                next_action=f"修复失败的测试后重跑完成门；命令：{cmd}",
                evidence_ids=ids + [test_run.evidence_id],
                finding_ids=fids,
            )
        trace_ok, trace_say, trace_next = _trace_note(rule, trace_guards or {})
        # 条件6 齐了也还不能颁 enforced：条件7（文档-实现版本一致）尚无机制，
        # 现在放行等于自称治理成立而实际没有——手册 16.4 点名的头号风险。
        return Verdict(
            rule_id=rule.rule_id,
            status="pass",
            absorption=Absorption.wired_and_tested,
            reason=(
                f"消费者与回归证据齐备 [{markers}]，且本轮测试命令真实通过"
                f"（E4，{observed.get('duration_seconds')}s）；{trace_say}；"
                + ("enforced 仅剩条件7（文档-实现一致性）未机制化"
                   if trace_ok else "enforced 还需条件6 与条件7（手册 6.5 七条件）")
            ),
            next_action=trace_next or "无",
            evidence_ids=ids + [test_run.evidence_id] + (trace_ids or []),
            finding_ids=fids,
        )

    # 没有 E4 有两种原因，给出的下一步完全不同：声明过（本轮是普通 audit，没跑）
    # vs 没声明（这个项目永远不会产 E4）。混为一谈会对已声明的项目重复劝说去声明。
    if declared_command is not None:
        return Verdict(
            rule_id=rule.rule_id,
            status="pass",
            absorption=Absorption.wired_and_tested,
            reason=(
                f"消费者与回归证据齐备 [{markers}]；本轮未执行测试命令（普通 audit 不跑），"
                f"回归性仅由测试路径引用推断（E3）；enforced 还需 E4 回归与条件6/7（手册 6.5 七条件）"
            ),
            next_action=f"跑完成门（sopctl task verify）以真实执行 {declared_command} 换取 E4 证据",
            evidence_ids=ids,
            finding_ids=fids,
        )

    return Verdict(
        rule_id=rule.rule_id,
        status="pass",
        absorption=Absorption.wired_and_tested,
        reason=(
            f"消费者与回归证据齐备 [{markers}]；项目未声明 test_command，永不产 E4，"
            f"回归性仅由测试路径引用推断；enforced 还需要运行时 trace 证据（手册 6.5 七条件）"
        ),
        next_action="声明 .sopcontrol/manifest.yaml 的 test_command（sopctl test-command --set ...），让完成门用真实退出码换 E4 证据",
        evidence_ids=ids,
        finding_ids=fids,
    )


def evaluate_all(rules: list[Rule], evidence: list[Evidence], findings: list[Finding]) -> list[Verdict]:
    return [evaluate_rule(r, evidence, findings) for r in rules]

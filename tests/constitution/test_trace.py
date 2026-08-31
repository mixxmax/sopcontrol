"""运行时 trace 证据：证明「本轮规则真的被加载并作出决策」（手册 6.5 条件6）。

这组测试守的是五件会悄悄骗人的事：

1. 决策函数仍然纯：落盘在 CLI 层，check_tool_call 一个字节都不写（宪法）。
2. 每条决策分支带的 rule_ids 必须是已声明的 guard，且没有分支凭空捏造 id。
3. allow 也要留痕：只记 deny 的日志只能证明「拦截器会拒绝」，证不了「拦截器跑过」。
4. trace 随日志本身衰减：陈旧日志不得续命成「本轮生效」。
5. 条件6 满足与否必须写进 reason，且单靠它不足以颁 enforced（还需条件5/7 的确认书）。

第 5 条是本机制最危险的地方：一旦允许「条件6 齐了就 enforced」，就会出现
自称治理成立而实际没有的状态——手册 16.4 点名的头号风险。
"""
import builtins
import json
from datetime import datetime, timedelta, timezone

from sopcontrol.harness import GUARD_IDS, GUARD_NO_VERIFY, GUARD_PUSH_GATE, check_tool_call
from sopcontrol.model import (
    Absorption,
    Evidence,
    Modality,
    Rule,
    RuleLifecycleEvent,
    RuleStatus,
    SourceRef,
    utcnow,
)
from sopcontrol.testrun import TEST_RUN_KIND
from sopcontrol.trace import (
    FRESH_WINDOW,
    MAX_EVENTS,
    TRACE_KIND,
    append_event,
    load_events,
    trace_evidence,
    trace_path,
)
from sopcontrol.verdict import evaluate_rule, fresh_trace_guards


def _rule(guard_ids=None) -> Rule:
    return Rule(
        rule_id="TRACE-001",
        statement="受控入口必须经拦截器决策",
        modality=Modality.MUST,
        status=RuleStatus.accepted,
        source=SourceRef(type="manual_seed", ref="tests"),
        consumer_markers=["trace_marker"],
        guard_ids=guard_ids or [],
    )


def _wired_evidence() -> list[Evidence]:
    return [
        Evidence(
            kind="ast_scan.references",
            subject="src/app.py",
            observed=["trace_marker"],
            observer="ast_scan",
            input_hash="prod1",
        ),
        Evidence(
            kind="ast_scan.references",
            subject="tests/test_app.py",
            observed=["trace_marker"],
            observer="ast_scan",
            input_hash="test1",
        ),
    ]


def _test_run(passed: bool = True) -> Evidence:
    return Evidence(
        kind=TEST_RUN_KIND,
        subject=".sopcontrol/manifest.yaml",
        observed={
            "command": "pytest -q",
            "exit_code": 0 if passed else 1,
            "passed": passed,
            "duration_seconds": 1.5,
            "timed_out": False,
        },
        observer="test_run",
        level=4,
        input_hash="digest1",
    )


# ---- 1. 纯度：决策不写盘 -------------------------------------------------

def test_decision_function_writes_nothing(tmp_path, monkeypatch):
    """check_tool_call 不得碰磁盘：trace 是 CLI 层的副作用，不是决策的一部分。"""
    def no_open(*args, **kwargs):
        raise AssertionError("决策函数不得做 I/O（宪法：纯函数）")

    monkeypatch.setattr(builtins, "open", no_open)
    d = check_tool_call({"tool_name": "Bash", "tool_input": {"command": "git push --no-verify"}})
    assert d.permissionDecision == "deny"
    assert not trace_path(tmp_path).exists()


# ---- 2. rule_ids 只能是已声明的 guard -----------------------------------

def test_every_branch_reports_only_declared_guards():
    """任何分支都不许返回 GUARD_IDS 之外的 id：否则 trace 里会出现幽灵规则。"""
    probes = [
        ("Write", {"file_path": ".sopcontrol/rules/registry.yaml", "content": "x"}),
        ("Write", {"file_path": ".claude/settings.json", "content": "x"}),
        ("Write", {"file_path": "src/app.py", "content": "x"}),
        ("Edit", {"file_path": "src/app.py", "old_string": "a", "new_string": "b"}),
        ("Bash", {"command": "git commit --no-verify -m x"}),
        ("Bash", {"command": "echo x > .sopcontrol/manifest.yaml"}),
        ("Bash", {"command": "git push origin main"}),
        ("Bash", {"command": "pytest -q"}),
        ("Read", {"file_path": "src/app.py"}),
    ]
    for tool, tool_input in probes:
        d = check_tool_call({"tool_name": tool, "tool_input": tool_input})
        unknown = set(d.rule_ids) - set(GUARD_IDS)
        assert not unknown, f"{tool} {tool_input} 报出未声明的 guard: {unknown}"


def test_claude_payload_omits_rule_ids():
    """rule_ids 是 sopctl 自己的字段；Claude PreToolUse schema 不接受额外键。"""
    payload = check_tool_call(
        {"tool_name": "Bash", "tool_input": {"command": "git push --no-verify"}}
    ).claude_payload()
    assert "rule_ids" not in json.dumps(payload)


def test_unmatched_tool_claims_no_guard():
    """没有 guard 参与的调用必须报空——否则 trace 会记下一次没发生的决策。"""
    d = check_tool_call({"tool_name": "Read", "tool_input": {"file_path": "a.py"}})
    assert d.permissionDecision == "allow"
    assert d.rule_ids == []


# ---- 3. allow 也留痕 ------------------------------------------------------

def test_allow_events_are_recorded_too(tmp_path):
    """只记 deny 的日志证明不了「加载过」，只证明「拒绝过」。条件6 要的是前者。"""
    append_event(tmp_path, tool="Bash", decision="allow", rule_ids=[GUARD_NO_VERIFY])
    ev = trace_evidence(tmp_path)
    assert ev is not None
    guards = ev.observed["guards"]
    assert guards[GUARD_NO_VERIFY]["decisions"] == ["allow"]
    assert guards[GUARD_NO_VERIFY]["count"] == 1


def test_evidence_level_is_four(tmp_path):
    """运行时事实是 E4，不是控制器读源码的 E3 推断。"""
    append_event(tmp_path, tool="Bash", decision="deny", rule_ids=[GUARD_PUSH_GATE])
    ev = trace_evidence(tmp_path)
    assert ev is not None and ev.level == 4 and ev.kind == TRACE_KIND


def test_no_log_means_no_evidence(tmp_path):
    """没日志就不铸证据——不许用空日志冒充「跑过但没触发」。"""
    assert trace_evidence(tmp_path) is None
    append_event(tmp_path, tool="Read", decision="allow", rule_ids=[])
    assert load_events(tmp_path)          # 事件本身记下了
    assert trace_evidence(tmp_path) is None  # 但没有 guard 参与 → 无 guard 证据


def test_log_is_bounded(tmp_path):
    """日志有上界：控制器不许把目标项目撑爆。"""
    for i in range(MAX_EVENTS + 20):
        append_event(tmp_path, tool="Bash", decision="allow", rule_ids=[GUARD_NO_VERIFY], detail=str(i))
    events = load_events(tmp_path)
    assert len(events) == MAX_EVENTS
    assert events[-1]["detail"] == str(MAX_EVENTS + 19)  # 丢的是最旧的


def test_corrupt_lines_are_skipped_not_fatal(tmp_path):
    append_event(tmp_path, tool="Bash", decision="deny", rule_ids=[GUARD_PUSH_GATE])
    path = trace_path(tmp_path)
    path.write_text(path.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    ev = trace_evidence(tmp_path)
    assert ev is not None and GUARD_PUSH_GATE in ev.observed["guards"]


# ---- 4. 衰减 -------------------------------------------------------------

def test_stale_log_expires(tmp_path):
    """证据随日志衰减，不随读取时刻续命：三个月前拦截过不证明今天生效。"""
    old = (utcnow() - FRESH_WINDOW - timedelta(days=1)).isoformat()
    trace_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    trace_path(tmp_path).write_text(
        json.dumps({"at": old, "tool": "Bash", "decision": "deny", "rule_ids": [GUARD_PUSH_GATE]}) + "\n",
        encoding="utf-8",
    )
    ev = trace_evidence(tmp_path)
    assert ev is not None
    assert ev.is_expired() is True     # run_audit 的过期过滤会把它丢掉
    assert fresh_trace_guards([]) == {}


def test_fresh_log_is_valid(tmp_path):
    append_event(tmp_path, tool="Bash", decision="deny", rule_ids=[GUARD_PUSH_GATE])
    ev = trace_evidence(tmp_path)
    assert ev is not None and ev.is_expired() is False


def test_naive_timestamp_fails_closed(tmp_path):
    """手工编辑过的裸时间戳无法证明新鲜 → 必定过期（fail-closed）。"""
    trace_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    trace_path(tmp_path).write_text(
        json.dumps({"at": "2099-01-01T00:00:00", "tool": "Bash",
                    "decision": "deny", "rule_ids": [GUARD_PUSH_GATE]}) + "\n",
        encoding="utf-8",
    )
    ev = trace_evidence(tmp_path)
    assert ev is not None and ev.is_expired() is True


# ---- 5. 判定：条件6 写进 reason，但单靠它不够 --------------------------

def test_fresh_trace_guards_ignores_low_level_evidence():
    """E3 冒充 trace 不算：条件6 只认运行时事实。"""
    fake = Evidence(
        kind=TRACE_KIND,
        subject="x",
        observed={"guards": {GUARD_PUSH_GATE: {"count": 1}}},
        observer="liar",
        level=3,
        input_hash="h",
    )
    assert fresh_trace_guards([fake]) == {}


def test_rule_without_guard_is_not_punished_but_never_enforced():
    """大多数规则靠代码接线执行，缺 trace 不算失败——但也永远到不了 enforced。"""
    v = evaluate_rule(_rule(), _wired_evidence() + [_test_run(True)], [])
    assert v.status == "pass"
    assert v.absorption == Absorption.wired_and_tested
    assert "未绑定运行时 guard" in v.reason
    assert "guard_ids" in v.next_action


def test_declared_guard_without_trace_points_at_installation():
    """绑了 guard 却没有运行时记录：下一步必须指向装/跑拦截器。"""
    v = evaluate_rule(_rule([GUARD_PUSH_GATE]), _wired_evidence() + [_test_run(True)], [])
    assert v.status == "pass"
    assert GUARD_PUSH_GATE in v.reason
    assert "无决策记录" in v.reason
    assert "hook" in v.next_action


def test_trace_satisfies_condition_six_but_enforced_still_withheld(tmp_path):
    """条件6 齐备仍不够：没有确认书（条件5/7）就停在 wired_and_tested。

    这是本机制最容易出错的一步。凑齐一条就放行等于自称治理成立而实际没有——
    手册 16.4 的头号风险。reason 必须同时说明已得到哪条、还缺哪条。
    """
    append_event(tmp_path, tool="Bash", decision="deny", rule_ids=[GUARD_PUSH_GATE])
    trace = trace_evidence(tmp_path)
    assert trace is not None

    v = evaluate_rule(
        _rule([GUARD_PUSH_GATE]),
        _wired_evidence() + [_test_run(True), trace],
        [],
    )
    assert v.status == "pass"
    assert v.absorption == Absorption.wired_and_tested   # 不是 enforced
    assert v.absorption != Absorption.enforced
    assert "条件6 满足" in v.reason
    assert "条件7" in v.reason
    assert trace.evidence_id in v.evidence_ids


def test_failing_tests_beat_trace(tmp_path):
    """有 trace 但测试没过仍然降级：运行时留痕不能替回归证据。"""
    append_event(tmp_path, tool="Bash", decision="deny", rule_ids=[GUARD_PUSH_GATE])
    trace = trace_evidence(tmp_path)
    v = evaluate_rule(
        _rule([GUARD_PUSH_GATE]),
        _wired_evidence() + [_test_run(False), trace],
        [],
    )
    assert v.status == "gap"
    assert v.absorption == Absorption.wired


def test_trace_judgement_stays_pure(monkeypatch, tmp_path):
    """条件6 的判定不得引入 I/O：判定器仍是纯函数（宪法）。"""
    append_event(tmp_path, tool="Bash", decision="deny", rule_ids=[GUARD_PUSH_GATE])
    trace = trace_evidence(tmp_path)

    def no_open(*args, **kwargs):
        raise AssertionError("判定器不得做任何 I/O（宪法：纯函数）")

    monkeypatch.setattr(builtins, "open", no_open)
    v = evaluate_rule(_rule([GUARD_PUSH_GATE]), _wired_evidence() + [_test_run(True), trace], [])
    assert v.status == "pass"


def test_trace_cutoff_is_inclusive_and_rejects_previous_microsecond():
    cutoff = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    rule = Rule(
        rule_id="TRACE-001",
        statement="受控入口必须经拦截器决策",
        modality=Modality.MUST,
        status=RuleStatus.accepted,
        source=SourceRef(type="manual_seed", ref="tests"),
        consumer_markers=["trace_marker"],
        guard_ids=[GUARD_PUSH_GATE],
        scope_paths=["src", "tests"],
        lifecycle_revision=1,
        effective_since=cutoff,
        lifecycle_events=[RuleLifecycleEvent(
            action="narrow",
            actor="human-reviewer",
            reason="缩小作用域",
            at=cutoff,
            preview_id="trace-rev-1",
            revision=1,
            before_scope=[],
            after_scope=["src", "tests"],
        )],
    )

    def trace_at(at):
        return Evidence(
            kind=TRACE_KIND,
            subject=".sopcontrol/evidence/trace.jsonl",
            observed={"guards": {GUARD_PUSH_GATE: {
                "count": 1,
                "decisions": ["deny"],
                "last_at": at.isoformat(),
            }}},
            observer="harness_trace",
            level=4,
            input_hash=at.isoformat(),
        )

    equal = evaluate_rule(
        rule,
        _wired_evidence() + [_test_run(True), trace_at(cutoff)],
        [],
        at=cutoff,
    )
    before = evaluate_rule(
        rule,
        _wired_evidence() + [
            _test_run(True),
            trace_at(cutoff - timedelta(microseconds=1)),
        ],
        [],
        at=cutoff,
    )

    assert "条件6 满足" in equal.reason
    assert "当前 lifecycle revision" in before.reason


def _trace_fact(guards: dict[str, tuple[datetime | str, int]]) -> Evidence:
    observed = {
        "guards": {
            guard_id: {
                "count": count,
                "decisions": ["deny"],
                "last_at": at.isoformat() if isinstance(at, datetime) else at,
            }
            for guard_id, (at, count) in guards.items()
        }
    }
    return Evidence(
        kind=TRACE_KIND,
        subject=".sopcontrol/evidence/trace.jsonl",
        observed=observed,
        observer="harness_trace",
        level=4,
        input_hash=str(observed),
    )


def test_unrelated_fresh_guard_does_not_renew_stale_guard():
    """Evidence 的全局有效期不能让 B 的新事件替 A 的旧事件续命。"""
    check_at = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    trace = _trace_fact({
        GUARD_PUSH_GATE: (check_at - FRESH_WINDOW - timedelta(microseconds=1), 1),
        GUARD_NO_VERIFY: (check_at, 1),
    })

    verdict = evaluate_rule(
        _rule([GUARD_PUSH_GATE]),
        _wired_evidence() + [_test_run(True), trace],
        [],
        at=check_at,
    )

    assert verdict.absorption == Absorption.wired_and_tested
    assert GUARD_PUSH_GATE in verdict.reason
    assert "新鲜" in verdict.reason


def test_all_declared_guards_must_be_fresh():
    """多 guard 规则中任一 guard 陈旧，条件6整体失败。"""
    check_at = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    trace = _trace_fact({
        GUARD_PUSH_GATE: (check_at, 3),
        GUARD_NO_VERIFY: (check_at - FRESH_WINDOW - timedelta(microseconds=1), 2),
    })

    verdict = evaluate_rule(
        _rule([GUARD_PUSH_GATE, GUARD_NO_VERIFY]),
        _wired_evidence() + [_test_run(True), trace],
        [],
        at=check_at,
    )

    assert verdict.absorption == Absorption.wired_and_tested
    assert GUARD_NO_VERIFY in verdict.reason
    assert "新鲜" in verdict.reason


def test_fresh_window_cutoff_is_inclusive_and_previous_microsecond_is_stale():
    check_at = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    cutoff = check_at - FRESH_WINDOW

    equal = evaluate_rule(
        _rule([GUARD_PUSH_GATE]),
        _wired_evidence() + [_test_run(True), _trace_fact({GUARD_PUSH_GATE: (cutoff, 1)})],
        [],
        at=check_at,
    )
    before = evaluate_rule(
        _rule([GUARD_PUSH_GATE]),
        _wired_evidence() + [
            _test_run(True),
            _trace_fact({GUARD_PUSH_GATE: (cutoff - timedelta(microseconds=1), 1)}),
        ],
        [],
        at=check_at,
    )

    assert "条件6 满足" in equal.reason
    assert "新鲜" in before.reason


def test_future_dated_guard_event_fails_closed():
    check_at = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    trace = _trace_fact({GUARD_PUSH_GATE: (check_at + timedelta(microseconds=1), 1)})

    verdict = evaluate_rule(
        _rule([GUARD_PUSH_GATE]),
        _wired_evidence() + [_test_run(True), trace],
        [],
        at=check_at,
    )

    assert verdict.absorption == Absorption.wired_and_tested
    assert "未来" in verdict.reason


def test_invalid_and_naive_guard_times_fail_closed():
    check_at = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    for bad_time in ("not-a-time", "2026-09-10T12:00:00"):
        verdict = evaluate_rule(
            _rule([GUARD_PUSH_GATE]),
            _wired_evidence() + [
                _test_run(True),
                _trace_fact({GUARD_PUSH_GATE: (bad_time, 1)}),
            ],
            [],
            at=check_at,
        )
        assert verdict.absorption == Absorption.wired_and_tested
        assert GUARD_PUSH_GATE in verdict.reason


def test_multiple_trace_evidence_merges_each_guard_by_real_instant():
    check_at = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    older = _trace_fact({GUARD_PUSH_GATE: (check_at - timedelta(hours=2), 1)})
    newer = _trace_fact({GUARD_PUSH_GATE: (check_at - timedelta(hours=1), 4)})

    guards = fresh_trace_guards([newer, older], at=check_at)

    assert guards[GUARD_PUSH_GATE]["count"] == 4
    assert guards[GUARD_PUSH_GATE]["last_at"] == (check_at - timedelta(hours=1)).isoformat()


def test_automatic_recovery_requires_trace_strictly_after_suspension_cutoff():
    suspended_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    suspended_until = suspended_at + timedelta(days=1)
    check_at = suspended_until + timedelta(hours=1)
    rule = Rule(
        rule_id="TRACE-001",
        statement="受控入口必须经拦截器决策",
        modality=Modality.MUST,
        status=RuleStatus.accepted,
        source=SourceRef(type="manual_seed", ref="tests"),
        consumer_markers=["trace_marker"],
        guard_ids=[GUARD_PUSH_GATE],
        lifecycle_revision=1,
        effective_since=suspended_at,
        suspended_until=suspended_until,
        lifecycle_events=[RuleLifecycleEvent(
            action="suspend",
            actor="human-reviewer",
            reason="临时暂停",
            at=suspended_at,
            until=suspended_until,
            preview_id="trace-suspend-1",
            revision=1,
        )],
    )

    at_cutoff = evaluate_rule(
        rule,
        _wired_evidence() + [
            _test_run(True),
            _trace_fact({GUARD_PUSH_GATE: (suspended_until, 1)}),
        ],
        [],
        at=check_at,
    )
    after_cutoff = evaluate_rule(
        rule,
        _wired_evidence() + [
            _test_run(True),
            _trace_fact({GUARD_PUSH_GATE: (suspended_until + timedelta(microseconds=1), 1)}),
        ],
        [],
        at=check_at,
    )

    assert "恢复" in at_cutoff.reason
    assert "条件6 满足" in after_cutoff.reason


def test_attestation_evidence_rejects_empty_or_agent_signer():
    check_at = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    rule = _rule([GUARD_PUSH_GATE]).model_copy(update={"attested_revision": 0})
    trace = _trace_fact({GUARD_PUSH_GATE: (check_at, 1)})

    for signer in ("", "agent"):
        attestation = Evidence(
            kind="rule.attestation",
            subject="docs/rule.md",
            observed={
                "rule_id": rule.rule_id,
                "source_ref": "docs/rule.md",
                "matches": True,
                "bypass_note": True,
                "attested_revision": 0,
                "attested_by": signer,
            },
            observer="attestation",
            level=3,
            input_hash=f"attest-{signer}",
        )
        verdict = evaluate_rule(
            rule,
            _wired_evidence() + [_test_run(True), trace, attestation],
            [],
            at=check_at,
        )
        assert verdict.absorption == Absorption.wired_and_tested
        assert "人工确认" in verdict.reason

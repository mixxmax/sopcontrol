"""规则确认书：手册 6.5 条件5（bypass 分析）与条件7（文档-实现版本一致）。

这是项目里第一次真的颁发 enforced，所以这组测试同时守两个反方向的错：

1. 颁不出来（机制不可证伪）：七条件齐备时必须真的到 enforced，否则整套等级
   体系的顶层是装饰品，谁也没法验证它有没有生效。
2. 颁得太松（治理幻觉，手册 16.4）：源文档改一个字节、bypass 分析为空、
   出处不是仓内文件——任一情形都必须立刻退回 wired_and_tested。

第 2 条比第 1 条危险得多。enforced 的含义是「这条规则的执行已被证明」，
错颁一次就等于替用户签了一份他没看过的保证书。
"""
import builtins
import shutil
from datetime import datetime, timedelta, timezone

from sopcontrol.attest import ATTEST_KIND, AttestError, attestation_evidence, record_attestation
from sopcontrol.cli import main
from sopcontrol.harness import GUARD_PUSH_GATE
from sopcontrol.model import (
    Absorption,
    Evidence,
    Modality,
    Rule,
    RuleLifecycleEvent,
    RuleStatus,
    SourceRef,
)
from sopcontrol.registry import Registry
from sopcontrol.testrun import TEST_RUN_KIND
from sopcontrol.trace import append_event, trace_evidence
from sopcontrol.verdict import evaluate_rule, fresh_attestations

NOTE = "可绕过：手工编辑注册表 yaml 绕过 CLI；已由 pre-push 的账本校验覆盖，接受残余风险"
DOC = "docs/rules/push.md"


def _project(tmp_path):
    """带 .sopcontrol/ 的目标项目，外加一份可 hash 的规则出处文档。"""
    work = tmp_path / "proj"
    work.mkdir()
    shutil.copytree("corpus/fixtures/jobflow-preview", work, dirs_exist_ok=True)
    doc = work / DOC
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# 推送规则\n\n推送必须经过验证钩子。\n", encoding="utf-8")
    return work


def _registry(work):
    return Registry(work / ".sopcontrol" / "rules" / "registry.yaml")


def _add(work, rule_id="ATT-001", source_ref=DOC):
    return main([
        "rule", "add", str(work),
        "--id", rule_id,
        "--statement", "推送必须经过验证钩子",
        "--source-ref", source_ref,
        "--guard-id", GUARD_PUSH_GATE,
        "--consumer-marker", "trace_marker",
    ])


def _attest(work, rule_id="ATT-001", note=NOTE, *extra):
    return main(["rule", "attest", rule_id, str(work), "--bypass-note", note, *extra])


def _rule(guard_ids=None) -> Rule:
    return Rule(
        rule_id="ATT-001",
        statement="推送必须经过验证钩子",
        modality=Modality.MUST,
        status=RuleStatus.accepted,
        source=SourceRef(type="document", ref=DOC),
        consumer_markers=["trace_marker"],
        guard_ids=guard_ids or [GUARD_PUSH_GATE],
    )


def _authoritative_rule(work) -> Rule:
    """使用 registry 的 lifecycle/attestation 事实，仅切换判定所需状态。"""
    return _registry(work).get("ATT-001").model_copy(
        update={"status": RuleStatus.accepted}
    )


def _wired() -> list[Evidence]:
    return [
        Evidence(kind="ast_scan.references", subject="src/app.py",
                 observed=["trace_marker"], observer="ast_scan", input_hash="p1"),
        Evidence(kind="ast_scan.references", subject="tests/test_app.py",
                 observed=["trace_marker"], observer="ast_scan", input_hash="t1"),
    ]


def _test_run(passed: bool = True) -> Evidence:
    return Evidence(
        kind=TEST_RUN_KIND,
        subject=".sopcontrol/manifest.yaml",
        observed={"command": "pytest -q", "exit_code": 0 if passed else 1,
                  "passed": passed, "duration_seconds": 1.5, "timed_out": False},
        observer="test_run",
        level=4,
        input_hash="d1",
    )


def _full_evidence(work, rules):
    """七条件所需的全套本轮证据：E4 回归 + 运行时 trace + 规则确认书。"""
    append_event(work, tool="Bash", decision="deny", rule_ids=[GUARD_PUSH_GATE])
    trace = trace_evidence(work)
    assert trace is not None
    return _wired() + [_test_run(True), trace] + attestation_evidence(work, rules)


# ---- 1. CLI 接线：命令行真的能把确认书写进注册表 ------------------------

def test_attest_reaches_the_registry(tmp_path):
    """--bypass-note 与源文档 hash 必须真的落盘。

    这正是 guard_ids 当年栽过的坑（见 tests/gate/test_rule_cli.py）：模型有字段、
    判定器会读，但命令行没接线 → 现实中没有一条规则可能满足条件。
    """
    work = _project(tmp_path)
    assert _add(work) == 0
    assert _attest(work) == 0

    rule = _registry(work).get("ATT-001")
    assert rule.bypass_note == NOTE
    assert len(rule.source_hash) == 16          # content_hash 截断长度
    assert rule.attested_by == "user"
    assert rule.attested_at is not None


def test_attest_requires_a_human_signer(tmp_path):
    """确认书必须由人签署；大小写或空白不能让 agent 自签变得有效。"""
    work = _project(tmp_path)
    assert _add(work) == 0
    before = _registry(work).path.read_bytes()

    for actor in ("", "  ", "agent", " AGENT "):
        assert _attest(work, "ATT-001", NOTE, "--by", actor) == 2
        assert _registry(work).path.read_bytes() == before
        assert _registry(work).get("ATT-001").source_hash == ""


def test_attest_rejects_source_paths_outside_the_project_or_through_symlinks(tmp_path):
    work = _project(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    escaped = work / "docs" / "escaped.md"
    escaped.symlink_to(outside)

    for index, source_ref in enumerate((str(outside), "../outside.md", "docs/escaped.md"), 1):
        rule_id = f"ATT-ESCAPE-{index}"
        assert _add(work, rule_id, source_ref=source_ref) == 0
        before = _registry(work).path.read_bytes()
        assert _attest(work, rule_id) == 2
        assert _registry(work).path.read_bytes() == before
        assert _registry(work).get(rule_id).source_hash == ""


def test_attest_rejects_source_path_through_symlinked_parent_directory(tmp_path):
    work = _project(tmp_path)
    real_docs = work / "real-docs"
    real_docs.mkdir()
    (real_docs / "rule.md").write_text("仓内真实规则文档", encoding="utf-8")
    (work / "linked-docs").symlink_to(real_docs, target_is_directory=True)
    assert _add(work, "ATT-SYMLINK-PARENT", source_ref="linked-docs/rule.md") == 0
    before = _registry(work).path.read_bytes()

    assert _attest(work, "ATT-SYMLINK-PARENT") == 2
    assert _registry(work).path.read_bytes() == before
    assert _registry(work).get("ATT-SYMLINK-PARENT").source_hash == ""


def test_attest_rejects_leaf_replaced_by_symlink_at_open_seam(tmp_path, monkeypatch):
    work = _project(tmp_path)
    assert _add(work) == 0
    registry = _registry(work)
    before = registry.path.read_bytes()
    source = work / DOC
    outside = tmp_path / "outside-raced.md"
    outside.write_text("EXTERNAL SECRET", encoding="utf-8")

    import sopcontrol.attest as attest_module

    original_open = attest_module.os.open
    replaced = False

    def replace_before_leaf_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if path == source.name and kwargs.get("dir_fd") is not None and not replaced:
            replaced = True
            source.unlink()
            source.symlink_to(outside)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(attest_module.os, "open", replace_before_leaf_open)

    assert _attest(work) == 2
    assert replaced is True
    assert registry.path.read_bytes() == before
    assert registry.get("ATT-001").source_hash == ""


def test_empty_bypass_note_is_rejected(tmp_path):
    """空白 bypass 分析不算分析（条件5）。

    机制能保证的只有「非空」，保证不了「写对」——所以这里守的是下限：
    空着就一定没想过。声称更多就是治理幻觉（手册 16.4）。
    """
    work = _project(tmp_path)
    assert _add(work) == 0
    assert _attest(work, "ATT-001", "   ") == 2
    assert _registry(work).get("ATT-001").source_hash == ""


def test_non_file_source_ref_cannot_be_attested(tmp_path):
    """出处是对话引用时无从绑定版本，必须拒绝而不是绑个空 hash。

    大量规则来自对话，本来就没有可 hash 的版本。诚实的结果是「这条规则拿不到
    enforced」，不是「假装绑定成功」。
    """
    work = _project(tmp_path)
    assert _add(work, "ATT-002", source_ref="2026-08-20 与用户的对话") == 0
    assert _attest(work, "ATT-002") == 2
    assert _registry(work).get("ATT-002").source_hash == ""


def test_unknown_rule_id_is_rejected(tmp_path):
    work = _project(tmp_path)
    assert _attest(work, "NOPE-999") == 2


def test_record_attestation_raises_on_empty_note(tmp_path):
    """CLI 之外直接调库也不能绕过条件5。"""
    work = _project(tmp_path)
    assert _add(work) == 0
    try:
        record_attestation(work, "ATT-001", bypass_note="", by="user")
    except AttestError as exc:
        assert "绕过分析" in str(exc)
    else:
        raise AssertionError("空 bypass 分析必须抛 AttestError")


# ---- 2. 证据：hash 比对的四种结局 ---------------------------------------

def test_evidence_matches_right_after_attest(tmp_path):
    work = _project(tmp_path)
    assert _add(work) == 0
    assert _attest(work) == 0

    evs = attestation_evidence(work, _registry(work).load())
    ev = next(e for e in evs if e.observed["rule_id"] == "ATT-001")
    assert ev.observed["matches"] is True
    assert ev.observed["detail"] == ""


def test_one_byte_change_breaks_the_binding(tmp_path):
    """源文档改一个字节，条件7 立刻不成立——不需要谁记得来撤销。

    这是条件7 的全部意义：规则是从某份文档的某个版本编译出来的，文档变了，
    这条规则就不再确定仍然忠于它的出处，哪怕代码一个字没动。
    """
    work = _project(tmp_path)
    assert _add(work) == 0
    assert _attest(work) == 0

    doc = work / DOC
    doc.write_text(doc.read_text(encoding="utf-8") + "x", encoding="utf-8")

    ev = attestation_evidence(work, _registry(work).load())[0]
    assert ev.observed["matches"] is False
    assert "修改" in ev.observed["detail"]


def test_deleted_source_file_is_recorded_as_mismatch(tmp_path):
    """出处被删/改名必须明确记成不一致，不能安静地不产证据。

    安静不产与「从未 attest」在判定器眼里无法区分，删掉源文档就会变成
    一条静默的提级路径。
    """
    work = _project(tmp_path)
    assert _add(work) == 0
    assert _attest(work) == 0
    (work / DOC).unlink()

    ev = attestation_evidence(work, _registry(work).load())[0]
    assert ev.observed["matches"] is False
    assert ev.observed["current"] is None
    assert "不存在" in ev.observed["detail"]


def test_evidence_rejects_leaf_replaced_by_symlink_at_open_seam(tmp_path, monkeypatch):
    work = _project(tmp_path)
    assert _add(work) == 0
    assert _attest(work) == 0
    rules = _registry(work).load()
    source = work / DOC
    outside = tmp_path / "outside-evidence-raced.md"
    outside.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    import sopcontrol.attest as attest_module

    original_open = attest_module.os.open
    replaced = False

    def replace_before_leaf_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if path == source.name and kwargs.get("dir_fd") is not None and not replaced:
            replaced = True
            source.unlink()
            source.symlink_to(outside)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(attest_module.os, "open", replace_before_leaf_open)

    ev = attestation_evidence(work, rules)[0]
    assert replaced is True
    assert ev.observed["matches"] is False
    assert ev.observed["current"] is None
    assert ev.input_hash != rules[0].source_hash


def test_unattested_rule_produces_no_evidence(tmp_path):
    """没做确认书的规则不产证据 → 判定器看不到就不颁 enforced（fail-closed）。"""
    work = _project(tmp_path)
    assert _add(work) == 0
    assert attestation_evidence(work, _registry(work).load()) == []


def test_evidence_level_is_three_not_four(tmp_path):
    """文档一致性是控制器读文件得出的事实（E3），不是运行时行为（E4）。

    把它标成 E4 就是拿读文件冒充实测——手册 4.3 的等级划分会立刻失去意义。
    """
    work = _project(tmp_path)
    assert _add(work) == 0
    assert _attest(work) == 0
    ev = attestation_evidence(work, _registry(work).load())[0]
    assert ev.level == 3
    assert ev.kind == ATTEST_KIND


def test_evidence_does_not_carry_the_note_text(tmp_path):
    """证据里只记「有没有写」，不搬正文：判定器只需要布尔，账本不该被长文撑大。"""
    work = _project(tmp_path)
    assert _add(work) == 0
    assert _attest(work) == 0
    ev = attestation_evidence(work, _registry(work).load())[0]
    assert ev.observed["bypass_note"] is True
    assert NOTE not in str(ev.observed)


# ---- 3. 判定：enforced 真的颁得出来，也真的撤得掉 -----------------------

def test_enforced_is_granted_when_all_seven_conditions_hold(tmp_path):
    """七条件齐备必须真的到 enforced。

    缺了这个正例，整套 enforced 机制不可证伪：所有其他测试都在证明
    「什么时候不颁」，而一个永远不颁的等级和不存在没有区别。
    """
    work = _project(tmp_path)
    assert _add(work) == 0
    assert _attest(work) == 0

    v = evaluate_rule(
        _authoritative_rule(work),
        _full_evidence(work, _registry(work).load()),
        [],
    )
    assert v.status == "pass"
    assert v.absorption == Absorption.enforced
    assert "七条件齐备" in v.reason
    assert v.next_action == "无"


def test_enforced_is_revoked_when_source_doc_changes(tmp_path):
    """源文档一改，下一轮 audit 自动降级——这是条件7 想拦的那件事。"""
    work = _project(tmp_path)
    assert _add(work) == 0
    assert _attest(work) == 0
    doc = work / DOC
    doc.write_text(doc.read_text(encoding="utf-8") + "\n补充一句。\n", encoding="utf-8")

    v = evaluate_rule(
        _authoritative_rule(work),
        _full_evidence(work, _registry(work).load()),
        [],
    )
    assert v.absorption == Absorption.wired_and_tested
    assert "确认书失效" in v.reason
    assert "attest" in v.next_action


def test_missing_attestation_withholds_enforced(tmp_path):
    """条件6 齐、条件5/7 缺：停在 wired_and_tested，且 reason 说清缺哪条。"""
    work = _project(tmp_path)
    assert _add(work) == 0

    v = evaluate_rule(_rule(), _full_evidence(work, _registry(work).load()), [])
    assert v.absorption == Absorption.wired_and_tested
    assert "条件5" in v.reason and "条件7" in v.reason
    assert "rule attest" in v.next_action


def test_attestation_without_trace_still_withholds_enforced(tmp_path):
    """反过来也一样：确认书齐但没有运行时 trace（条件6），照样不颁。"""
    work = _project(tmp_path)
    assert _add(work) == 0
    assert _attest(work) == 0

    evidence = _wired() + [_test_run(True)] + attestation_evidence(work, _registry(work).load())
    v = evaluate_rule(_rule(), evidence, [])
    assert v.absorption == Absorption.wired_and_tested
    assert "条件6" in v.reason


def test_failing_tests_beat_attestation(tmp_path):
    """确认书不能替回归证据：测试没过仍然降到 wired。"""
    work = _project(tmp_path)
    assert _add(work) == 0
    assert _attest(work) == 0

    append_event(work, tool="Bash", decision="deny", rule_ids=[GUARD_PUSH_GATE])
    evidence = (_wired() + [_test_run(False), trace_evidence(work)]
                + attestation_evidence(work, _registry(work).load()))
    v = evaluate_rule(_rule(), evidence, [])
    assert v.status == "gap"
    assert v.absorption == Absorption.wired


def test_forged_attestation_evidence_cannot_claim_match():
    """伪造的确认书证据里 matches=False 就是不成立——判定器只读结论，不猜意图。"""
    fake = Evidence(
        kind=ATTEST_KIND,
        subject=DOC,
        observed={"rule_id": "ATT-001", "matches": False, "bypass_note": True,
                  "detail": "源文档在确认之后被修改"},
        observer="liar",
        level=3,
        input_hash="h",
    )
    assert fresh_attestations([fake])["ATT-001"]["matches"] is False


def test_attestation_judgement_stays_pure(monkeypatch, tmp_path):
    """条件5/7 的判定不得引入 I/O：hash 比对在 attest 层做完，判定器仍是纯函数。"""
    work = _project(tmp_path)
    assert _add(work) == 0
    assert _attest(work) == 0
    rules = _registry(work).load()
    rule = next(item for item in rules if item.rule_id == "ATT-001").model_copy(
        update={"status": RuleStatus.accepted}
    )
    evidence = _full_evidence(work, rules)

    def no_open(*args, **kwargs):
        raise AssertionError("判定器不得做任何 I/O（宪法：纯函数）")

    monkeypatch.setattr(builtins, "open", no_open)
    v = evaluate_rule(rule, evidence, [])
    assert v.absorption == Absorption.enforced


def test_attestation_revision_must_equal_current_lifecycle_revision():
    at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    rule = Rule(
        rule_id="ATT-001",
        statement="推送必须经过验证钩子",
        modality=Modality.MUST,
        status=RuleStatus.accepted,
        source=SourceRef(type="document", ref=DOC),
        consumer_markers=["trace_marker"],
        guard_ids=[GUARD_PUSH_GATE],
        scope_paths=["src", "tests"],
        lifecycle_revision=1,
        effective_since=at,
        attested_revision=1,
        lifecycle_events=[RuleLifecycleEvent(
            action="narrow",
            actor="human-reviewer",
            reason="缩小作用域",
            at=at,
            preview_id="rev-1",
            revision=1,
            before_scope=[],
            after_scope=["src", "tests"],
        )],
    )
    trace = Evidence(
        kind="harness.trace",
        subject=".sopcontrol/evidence/trace.jsonl",
        observed={"guards": {GUARD_PUSH_GATE: {
            "count": 1,
            "decisions": ["deny"],
            "last_at": at.isoformat(),
        }}},
        observer="harness_trace",
        level=4,
        input_hash="trace",
    )

    for revision in (0, 2):
        attestation = Evidence(
            kind=ATTEST_KIND,
            subject=DOC,
            observed={
                "rule_id": "ATT-001",
                "source_ref": DOC,
                "matches": True,
                "bypass_note": True,
                "attested_by": "human-reviewer",
                "attested_revision": revision,
            },
            observer="attestation",
            level=3,
            input_hash=f"attest-{revision}",
        )
        verdict = evaluate_rule(
            rule,
            _wired() + [_test_run(True), trace, attestation],
            [],
            at=at,
        )
        assert verdict.absorption == Absorption.wired_and_tested
        assert "lifecycle revision" in verdict.reason

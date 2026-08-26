"""E4 测试运行证据：真跑测试换吸收等级（手册 4.3）。

这组测试守的是四件事，每件都对应一个「会悄悄骗人」的失败模式：

1. 未声明 test_command → 不产 E4 → 判定与从前逐字一致（不因新机制误伤既有项目）。
2. 声明了且真跑通 → wired_and_tested，且理由里必须说清是 E4（不许用 E3 冒充）。
3. 声明了但没跑通 → 降回 wired/gap（跑过没过 ≠ 没跑过，必须留痕并降级）。
4. 源码改一个字节 → 上一轮的绿变 stale（绿灯不得跨越代码变更继续有效）。
"""
import builtins

from sopcontrol.model import Absorption, Evidence, Modality, Rule, RuleStatus, SourceRef
from sopcontrol.stale import is_input_stale
from sopcontrol.testrun import (
    TEST_DECL_KIND,
    TEST_RUN_KIND,
    declaration_evidence,
    load_test_command,
    run_test_command,
    should_run,
    source_digest,
)
from sopcontrol.verdict import declared_test_command, evaluate_rule, latest_test_run


def _rule() -> Rule:
    return Rule(
        rule_id="E4-001",
        statement="E4 闸门测试规则必须被接线",
        modality=Modality.MUST,
        status=RuleStatus.accepted,
        source=SourceRef(type="manual_seed", ref="tests"),
        consumer_markers=["e4_marker"],
    )


def _wired_evidence() -> list[Evidence]:
    """生产 + 测试路径都引用了消费者标记：E3 齐备，只差 E4。"""
    return [
        Evidence(
            kind="ast_scan.references",
            subject="src/app.py",
            observed=["e4_marker"],
            observer="ast_scan",
            input_hash="prod1",
        ),
        Evidence(
            kind="ast_scan.references",
            subject="tests/test_app.py",
            observed=["e4_marker"],
            observer="ast_scan",
            input_hash="test1",
        ),
    ]


def _test_run(passed: bool, **extra) -> Evidence:
    observed = {
        "command": "pytest -q",
        "exit_code": 0 if passed else 1,
        "passed": passed,
        "duration_seconds": 1.5,
        "timed_out": False,
        "source_digest": "digest1",
    }
    observed.update(extra)
    return Evidence(
        kind=TEST_RUN_KIND,
        subject=".sopcontrol/manifest.yaml",
        observed=observed,
        observer="test_run",
        level=4,
        input_hash="digest1",
    )


def _declaration(command: str = "pytest -q") -> Evidence:
    return Evidence(
        kind=TEST_DECL_KIND,
        subject=".sopcontrol/manifest.yaml",
        observed={"command": command},
        observer="test_run",
        level=3,
        input_hash="manifest1",
    )


def test_no_e4_keeps_legacy_semantics():
    """既没声明也没跑：判定与从前一致，理由必须如实说「未声明」。"""
    verdict = evaluate_rule(_rule(), _wired_evidence(), [])
    assert verdict.status == "pass"
    assert verdict.absorption == Absorption.wired_and_tested
    assert "未声明 test_command" in verdict.reason


def test_declared_but_not_run_says_so_and_points_at_the_gate():
    """声明过但本轮没跑（普通 audit）：不得再劝去声明，下一步应指向完成门。

    这一条守的是一个真实出现过的谎：manifest 里已经写了 test_command，audit
    却仍然打印「项目未声明 test_command」并建议去声明。判定器是纯函数看不见
    磁盘，所以「声明过」这件事必须以证据形态送进来，否则它只能猜。
    """
    verdict = evaluate_rule(_rule(), _wired_evidence() + [_declaration()], [])
    assert verdict.status == "pass"
    assert verdict.absorption == Absorption.wired_and_tested
    assert "未声明" not in verdict.reason
    assert "本轮未执行测试命令" in verdict.reason
    assert "task verify" in verdict.next_action
    assert "pytest -q" in verdict.next_action


def test_declaration_evidence_reflects_manifest(tmp_path):
    """声明证据必须来自 manifest 真实内容，没声明就不铸（不许凭空造事实）。"""
    assert declaration_evidence(tmp_path) is None

    sc = tmp_path / ".sopcontrol"
    sc.mkdir()
    (sc / "manifest.yaml").write_text("test_command: \"exit 0\"\n", encoding="utf-8")
    ev = declaration_evidence(tmp_path)
    assert ev is not None
    assert ev.kind == TEST_DECL_KIND
    assert ev.level == 3  # 只是读了一行配置，不是跑过测试
    assert ev.observed["command"] == "exit 0"
    assert declared_test_command([ev]) == "exit 0"


def test_declared_command_ignored_when_e4_present():
    """有 E4 时以真实退出码为准，声明只是背景事实，不得反过来影响结论。"""
    verdict = evaluate_rule(
        _rule(), _wired_evidence() + [_declaration(), _test_run(False)], []
    )
    assert verdict.status == "gap"
    assert verdict.absorption == Absorption.wired


def test_passing_e4_marks_evidence_level():
    verdict = evaluate_rule(_rule(), _wired_evidence() + [_test_run(True)], [])
    assert verdict.status == "pass"
    assert verdict.absorption == Absorption.wired_and_tested
    assert "E4" in verdict.reason


def test_failing_e4_degrades_to_wired():
    """跑过没过必须降级——这是本机制存在的唯一理由。"""
    run = _test_run(False)
    verdict = evaluate_rule(_rule(), _wired_evidence() + [run], [])
    assert verdict.status == "gap"
    assert verdict.absorption == Absorption.wired
    assert "退出码 1" in verdict.reason
    assert run.evidence_id in verdict.evidence_ids


def test_timeout_reported_as_not_passed():
    run = _test_run(False, exit_code=-1, timed_out=True)
    verdict = evaluate_rule(_rule(), _wired_evidence() + [run], [])
    assert verdict.status == "gap"
    assert "超时" in verdict.reason


def test_any_failing_run_wins():
    """同轮多条运行证据取最保守：任一失败即视为未通过。"""
    picked = latest_test_run([_test_run(True), _test_run(False)])
    assert picked is not None
    assert picked.observed["passed"] is False


def test_e4_gate_stays_pure(monkeypatch):
    """E4 分流不得引入 I/O：判定器仍是纯函数（宪法）。"""
    def no_open(*args, **kwargs):
        raise AssertionError("判定器不得做任何 I/O（宪法：纯函数）")

    monkeypatch.setattr(builtins, "open", no_open)
    verdict = evaluate_rule(_rule(), _wired_evidence() + [_test_run(True)], [])
    assert verdict.status == "pass"


def test_missing_manifest_means_no_test_command(tmp_path):
    assert load_test_command(tmp_path) is None
    assert should_run(tmp_path) is False
    assert run_test_command(tmp_path) is None


def test_declared_command_runs_and_mints_e4(tmp_path, monkeypatch):
    # 根 conftest 全局钉了递归自锁；本例要验证「真的会跑」，故显式解锁。
    # 命令是 exit 0，不会套娃。
    monkeypatch.delenv("SOPCONTROL_TEST_RUN_ACTIVE", raising=False)
    sc = tmp_path / ".sopcontrol"
    sc.mkdir()
    (sc / "manifest.yaml").write_text(
        "test_command: \"exit 0\"\n", encoding="utf-8"
    )
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")

    assert load_test_command(tmp_path) == "exit 0"
    ev = run_test_command(tmp_path)
    assert ev is not None
    assert ev.level == 4
    assert ev.observed["passed"] is True
    assert ev.observed["exit_code"] == 0

    # 源码没动：证据仍然新鲜
    assert is_input_stale(tmp_path, ev) is False
    # 源码动一个字节：上一轮的绿立刻失效
    (tmp_path / "app.py").write_text("x = 2\n", encoding="utf-8")
    assert is_input_stale(tmp_path, ev) is True


def test_failing_command_still_mints_evidence(tmp_path, monkeypatch):
    """跑失败不返回 None——「跑过且没过」必须留痕，否则等于没跑过。"""
    monkeypatch.delenv("SOPCONTROL_TEST_RUN_ACTIVE", raising=False)
    sc = tmp_path / ".sopcontrol"
    sc.mkdir()
    (sc / "manifest.yaml").write_text("test_command: \"exit 3\"\n", encoding="utf-8")

    ev = run_test_command(tmp_path)
    assert ev is not None
    assert ev.observed["passed"] is False
    assert ev.observed["exit_code"] == 3


def test_recursion_guard_blocks_nested_run(tmp_path, monkeypatch):
    """测试子进程内再触发完成门必须跳过，否则 pytest 套 pytest。"""
    from sopcontrol import testrun

    sc = tmp_path / ".sopcontrol"
    sc.mkdir()
    (sc / "manifest.yaml").write_text("test_command: \"exit 0\"\n", encoding="utf-8")

    monkeypatch.setenv(testrun.GUARD_ENV, "1")
    assert should_run(tmp_path) is False
    assert run_test_command(tmp_path) is None


def test_source_digest_ignores_excluded_dirs(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    before = source_digest(tmp_path)
    vendored = tmp_path / "node_modules" / "pkg"
    vendored.mkdir(parents=True)
    (vendored / "index.js").write_text("module.exports = 1\n", encoding="utf-8")
    assert source_digest(tmp_path) == before

"""CLI 层规则登记回归：守 guard_ids 这条从模型到命令行的接线。

这个文件存在的原因是一个「看起来齐全、实际不通」的漏洞：Rule.guard_ids 在模型里有、
判定器也读它（手册 6.5 条件6 靠它判断本轮规则是否真的被加载过），但 `rule add`
从来没有 --guard-id 参数——于是现实中没有任何一条注册表规则可能满足条件6。
模型字段 ✓、判定逻辑 ✓、测试 ✓，生产链路却是断的，正是手册 16.4 说的治理幻觉。

所以这里不测判定语义（那在 tests/constitution/test_trace.py），只测一件事：
命令行真的能把 guard 写进注册表，且写错名字当场被拒。
"""
import shutil

import pytest

from sopcontrol.cli import main
from sopcontrol.harness import GUARD_IDS
from sopcontrol.registry import Registry


def _project(tmp_path):
    work = tmp_path / "proj"
    work.mkdir()
    shutil.copytree("corpus/fixtures/jobflow-preview", work, dirs_exist_ok=True)
    return work


def _registry(work):
    return Registry(work / ".sopcontrol" / "rules" / "registry.yaml")


def _add(work, rule_id, *guard_args):
    return main([
        "rule", "add", str(work),
        "--id", rule_id,
        "--statement", "推送必须经过验证钩子",
        "--source-ref", "tests/gate/test_rule_cli.py",
        *guard_args,
    ])


def test_guard_id_reaches_the_registry(tmp_path):
    """--guard-id 必须真的落到 Rule.guard_ids，否则条件6 永远无从满足。"""
    work = _project(tmp_path)
    guard = "GUARD-PUSH-GATE"
    assert guard in GUARD_IDS, "测试用的 guard 名已从拦截器中消失，先修拦截器再改这里"

    assert _add(work, "TRACE-CLI-001", "--guard-id", guard) == 0

    rule = _registry(work).get("TRACE-CLI-001")
    assert rule.guard_ids == [guard]


def test_multiple_guard_ids_accumulate(tmp_path):
    """一条规则可以由多个 guard 共同执行，append 语义不能只留最后一个。"""
    work = _project(tmp_path)
    assert _add(
        work, "TRACE-CLI-002",
        "--guard-id", "GUARD-PUSH-GATE",
        "--guard-id", "GUARD-NO-VERIFY",
    ) == 0

    rule = _registry(work).get("TRACE-CLI-002")
    assert set(rule.guard_ids) == {"GUARD-PUSH-GATE", "GUARD-NO-VERIFY"}


def test_typo_in_guard_id_is_rejected_before_writing(tmp_path):
    """写错一个字母的 guard 名不许静默收下。

    拦截器永远不会用这个名字留痕，规则就会永久停在「声明了 guard 却拿不到 trace」，
    而真实错因只是拼写。当场拒（exit 2）并且不写注册表，比事后查判定便宜得多。
    """
    work = _project(tmp_path)
    before = {r.rule_id for r in _registry(work).load()}

    assert _add(work, "TRACE-CLI-003", "--guard-id", "GUARD-PUSH-GAT") == 2

    after = {r.rule_id for r in _registry(work).load()}
    assert after == before, "被拒的规则不该留在注册表里"


def test_rule_without_guard_still_registers(tmp_path):
    """绝大多数规则没有运行时 guard；不带 --guard-id 必须照常登记。"""
    work = _project(tmp_path)
    assert _add(work, "TRACE-CLI-004") == 0
    assert _registry(work).get("TRACE-CLI-004").guard_ids == []


def test_error_message_names_the_valid_guards(tmp_path, capsys):
    """报错要给出可用集合——否则用户只知道错了，不知道该写什么。"""
    work = _project(tmp_path)
    assert _add(work, "TRACE-CLI-005", "--guard-id", "NOPE") == 2

    err = capsys.readouterr().err
    for guard in GUARD_IDS:
        assert guard in err

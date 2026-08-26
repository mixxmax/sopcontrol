"""Bootstrap/Shadow 模式：手册 7.1 五项秩序、7.2 最小宪法、7.3 L0–L4 阶梯。

这组测试守的是一个比「功能是否可用」更要紧的东西：等级报告的诚实性。

成熟度是模型读到的第一行上下文——它决定了「门没拦我」该怎么解读。报高了，
弱模型会把 L1 的建议当成 L3 的许可（手册 16.4 的治理幻觉）；报低了，控制器
就成了狼来了，用户会开始绕过它。所以两个方向都要有反例：

- 该升不升（机制装了却不承认）→ test_ladder_climbs_*
- 该降不降（跳级也算数）→ test_skipped_rung_suspends_level
- 越权（Bootstrap 自动造硬门）→ test_scan_never_touches_registry / never_produces_findings

第 7 章的立场是「不等成熟架构，也不过早冻结设计」。冻结的方式不止一种：
把扫出来的候选直接变成规则是最隐蔽的一种，因为它看起来很勤快。
"""
import shutil
from pathlib import Path

import yaml

from sopcontrol.bootstrap import (
    MATURITY_KIND,
    RUNGS,
    SHADOW_ORDERS,
    assess_maturity,
    check_orders,
    load_constitution,
    maturity_evidence,
    save_constitution,
    scan_constitution,
)
from sopcontrol.cli import main
from sopcontrol.harness import GUARD_IDS, GUARD_PUSH_GATE
from sopcontrol.registry import Registry


def _greenfield(tmp_path, name="green"):
    """结构未明的新项目：只有 README 和一个源文件，没有 .sopcontrol/。

    第 7 章要解决的正是这种项目——不能要求它先成熟再被管。
    """
    work = tmp_path / name
    (work / "src").mkdir(parents=True)
    (work / "README.md").write_text(
        "# demo\n\n一个用来收发工单的小服务。\n", encoding="utf-8"
    )
    (work / "src" / "app.py").write_text(
        "import subprocess\n\n\ndef deploy():\n    subprocess.run(['echo', 'ship'])\n",
        encoding="utf-8",
    )
    return work


def _managed(tmp_path):
    """已被控制的项目：真源码 + 经 CLI 建起来的完整控制目录。

    刻意不直接拷语料夹具的 .sopcontrol/——夹具是为检测模式攒的，没有
    manifest.yaml，test-command 之类的命令会拒绝工作。经 init 建立才和
    真实项目同构。
    """
    work = tmp_path / "managed"
    (work / "src").mkdir(parents=True)
    for rel in ("src/gateway.py", "src/push_job.py", "docs/tracker-sop.md"):
        src = Path("corpus/fixtures/jobflow-preview") / rel
        dst = work / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    assert main(["init", str(work)]) == 0
    assert main([
        "rule", "add", str(work), "--id", "PUSH-001",
        "--statement", "推送前必须经过网关",
        "--source-ref", "docs/tracker-sop.md", "--status", "accepted",
    ]) == 0
    return work


# ---------- 7.3 阶梯：该升就升 ----------

def test_greenfield_reports_below_l0(tmp_path):
    """连账本都没有的项目报 none，且下一步指向 init——不是报错，是给路。"""
    report = assess_maturity(_greenfield(tmp_path))
    assert report.level == "none"
    assert report.next_rung == "L0"
    assert "init" in report.next_action
    assert all(not o["satisfied"] for o in report.orders)


def test_ladder_climbs_as_mechanisms_appear(tmp_path):
    """init → 有规则 → 声明验收命令：每装一件，等级必须真的往上走。

    这条测试的意义是让「等级」可证伪。如果装了机制等级不动，那这个数字
    就只是装饰，没人能用它判断项目状态。
    """
    work = _greenfield(tmp_path)
    assert main(["init", str(work)]) == 0
    assert assess_maturity(work).level == "L0"          # 账本就位 → 秩序3

    assert main([
        "rule", "add", str(work),
        "--id", "SHIP-001",
        "--statement", "部署前必须确认",
        "--source-ref", "README.md",
        "--status", "accepted",
    ]) == 0
    assert assess_maturity(work).level == "L1"          # 有生效规则 → 秩序1

    assert main(["test-command", str(work), "--set", "pytest -q"]) == 0
    assert assess_maturity(work).level == "L2"          # 有验收命令 → 秩序4


def test_l3_needs_both_interceptor_and_guard(tmp_path):
    """装了钩子但没有规则声明 guard_ids 不算 L3：拦得住动作，说不出依据。

    这是本模块从我们自己仓库里抓出来的真实缺口。分开检查两个条件，是因为
    「有拦截器」和「拦截由某条规则授权」是两件事——只有前者时，拦下来的
    动作无法回答「凭哪条规则」，用户也就无法复核或撤销它。
    """
    work = _greenfield(tmp_path)
    main(["init", str(work)])
    main(["test-command", str(work), "--set", "pytest -q"])
    main([
        "rule", "add", str(work), "--id", "SHIP-001",
        "--statement", "部署前必须确认", "--source-ref", "README.md",
        "--status", "accepted",
    ])
    (work / ".git" / "hooks").mkdir(parents=True)
    (work / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    by_id = {o["order_id"]: o for o in check_orders(work)}
    assert by_id["ORDER-2"]["satisfied"] is False
    assert "guard" in by_id["ORDER-2"]["detail"]
    assert assess_maturity(work).level == "L2"

    main([
        "rule", "add", str(work), "--id", "SHIP-002",
        "--statement", "推送必须经过终点门", "--source-ref", "README.md",
        "--status", "accepted", "--guard-id", GUARD_PUSH_GATE,
    ])
    assert assess_maturity(work).level == "L3"


# ---------- 7.3 阶梯：该降就降 ----------

def test_skipped_rung_suspends_level(tmp_path):
    """L4 有机制但 L2 缺失 → 报 L1，并明说高层治理被悬空。

    「取连续满足的最高一级」不是保守，是准确：规则有人签字，却没有任何东西
    能证明活干完了，这种项目的治理是纸面的。报 L4 会让人以为交付受控。
    """
    work = _greenfield(tmp_path)
    main(["init", str(work)])
    doc = work / "docs" / "sop.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# 规则\n\n部署前必须确认。\n", encoding="utf-8")
    main([
        "rule", "add", str(work), "--id", "SHIP-001",
        "--statement", "部署前必须确认", "--source-ref", "docs/sop.md",
        "--status", "accepted",
    ])
    assert main([
        "rule", "attest", "SHIP-001", str(work),
        "--bypass-note", "可手改 yaml 绕过；由 pre-push 账本校验覆盖",
    ]) == 0

    report = assess_maturity(work)
    by_rung = {o["rung"]: o for o in report.orders}
    assert by_rung["L4"]["satisfied"] is True       # 确认书确实在位
    assert by_rung["L2"]["satisfied"] is False      # 但没有验收命令
    assert report.level == "L1"                     # 断在缺口处，不跳级
    assert report.next_rung == "L2"
    assert "悬空" in report.reason and "L4" in report.reason


def test_every_rung_maps_to_exactly_one_order():
    """五项秩序与五级阶梯一一对应——映射是显式的，不是黑话。"""
    rungs = [r for r, _ in RUNGS]
    mapped = [o.rung for o in SHADOW_ORDERS]
    assert sorted(mapped) == sorted(rungs)
    assert len(set(mapped)) == len(SHADOW_ORDERS)


# ---------- 影子模式的边界：只报告，不造门 ----------

def test_shadow_orders_have_no_rule_ids():
    """秩序不是规则：没有 rule_id、不进注册表，所以不可能让门失败。"""
    for order in SHADOW_ORDERS:
        assert not hasattr(order, "rule_id")
        assert order.order_id.startswith("ORDER-")


def test_scan_never_touches_registry(tmp_path):
    """7.2 候选全部 proposed，且 --write 只写 constitution.yaml。

    「这些内容在初期是 proposed，不会自动成为永久硬门」——扫描顺手把候选
    塞进注册表，就是过早冻结设计，正是第 7 章禁止的。
    """
    work = _greenfield(tmp_path)
    main(["init", str(work)])
    before = Registry(work / ".sopcontrol" / "rules" / "registry.yaml").load()

    assert main(["bootstrap", str(work), "--write"]) == 0

    after = Registry(work / ".sopcontrol" / "rules" / "registry.yaml").load()
    assert [r.rule_id for r in after] == [r.rule_id for r in before]
    saved = load_constitution(work)
    assert saved and all(c["status"] == "proposed" for c in saved)


def test_scan_reports_unknowns_instead_of_silence(tmp_path):
    """扫不出来的类别转成「需要用户确认」，不静默。

    「没有敏感路径」和「没查出敏感路径」对使用者是两件完全不同的事；
    把后者说成前者，就是用沉默伪造了一个结论。
    """
    candidates = scan_constitution(_greenfield(tmp_path))
    unknowns = [c for c in candidates if c["category"] == "unknowns"]
    assert unknowns, "空缺必须显式登记"
    assert "敏感路径" in unknowns[0]["value"]


def test_scan_finds_purpose_and_side_effects(tmp_path):
    """README 第一句 → 项目目的；生产路径里的 subprocess → 副作用候选。"""
    candidates = scan_constitution(_greenfield(tmp_path))
    by_cat = {c["category"]: c for c in candidates}
    assert "工单" in by_cat["purpose"]["value"]
    assert "src/app.py" in by_cat["side_effects"]["value"]


def test_side_effect_scan_ignores_test_paths(tmp_path):
    """测试里的 subprocess 不是产品副作用——否则每个项目都会被误报。"""
    work = _greenfield(tmp_path, name="testonly")
    (work / "src" / "app.py").write_text("def noop():\n    return 1\n", encoding="utf-8")
    (work / "tests").mkdir()
    (work / "tests" / "test_app.py").write_text(
        "import subprocess\n\n\ndef test_x():\n    subprocess.run(['true'])\n", encoding="utf-8"
    )
    cats = {c["category"] for c in scan_constitution(work)}
    assert "side_effects" not in cats


# ---------- 证据层 ----------

def test_maturity_evidence_is_e3_not_e4(tmp_path):
    """成熟度是读文件得出的结论 → E3。说成 E4 就是把「机制在位」冒充「已验证」。"""
    work = _managed(tmp_path)
    ev = maturity_evidence(work)
    assert ev.kind == MATURITY_KIND
    assert ev.level == 3
    assert ev.observed["level"] in {"none", *[r for r, _ in RUNGS]}


def test_maturity_evidence_stales_when_level_changes(tmp_path):
    """等级变了，旧结论必须退场；没变则保持 fresh。

    subject 是 .sopcontrol/ 目录，没有单一文件可比 hash，所以 stale 判定要
    重算结论本身。反例是「派生结论一落盘即过期」——那样它永远进不了 explain。
    """
    from sopcontrol.stale import is_input_stale

    work = _managed(tmp_path)
    ev = maturity_evidence(work)
    assert is_input_stale(work, ev) is False

    main(["test-command", str(work), "--set", "pytest -q"])
    assert is_input_stale(work, ev) is True


def test_audit_mints_maturity_every_round(tmp_path):
    """每轮审计都重算成熟度：装了钩子、声明了验收命令，下一轮就该反映出来。"""
    from plugins import DETECTORS, SENSORS
    from sopcontrol.audit import run_audit

    work = _managed(tmp_path)
    report = run_audit(work, SENSORS, DETECTORS, persist=False)
    rows = [e for e in report.evidence if e.kind == MATURITY_KIND]
    assert len(rows) == 1


def test_bootstrap_never_produces_findings(tmp_path):
    """影子模式不产 Finding：产了就等于让门失败，那是过早冻结。"""
    from plugins import DETECTORS, SENSORS
    from sopcontrol.audit import run_audit

    work = _greenfield(tmp_path)
    main(["init", str(work)])
    report = run_audit(work, SENSORS, DETECTORS, persist=False)
    assert not [f for f in report.findings if "maturity" in f.pattern_id
                or "order" in f.pattern_id or "constitution" in f.pattern_id]


# ---------- CLI 接线 ----------

def test_cli_bootstrap_readonly_by_default(tmp_path, capsys):
    """不带 --write 时绝不落盘：预览必须真的是预览。"""
    work = _greenfield(tmp_path)
    main(["init", str(work)])
    assert main(["bootstrap", str(work)]) == 0
    assert not (work / ".sopcontrol" / "constitution.yaml").exists()
    assert "proposed" in capsys.readouterr().out


def test_cli_bootstrap_json_is_machine_readable(tmp_path, capsys):
    """--json 供 harness 消费：等级、缺口、候选一次给全。"""
    import json

    work = _managed(tmp_path)
    capsys.readouterr()  # 丢掉 _managed 建项目时的 CLI 输出
    assert main(["bootstrap", str(work), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["level"] in {"none", *[r for r, _ in RUNGS]}
    assert len(payload["orders"]) == len(SHADOW_ORDERS)
    assert isinstance(payload["constitution"], list)


def test_cli_bootstrap_works_without_sopcontrol(tmp_path):
    """未初始化的项目不能崩：第 7 章的场景恰恰是「还没被管起来」。"""
    assert main(["bootstrap", str(_greenfield(tmp_path))]) == 0


# ---------- 投影 ----------

def test_projection_carries_maturity_level(tmp_path):
    """模型只看投影：等级和下一级缺口必须出现在那一节里。

    check_projections 一律按 `project all` 的提示语重算，所以这里也走
    write_all_projections——写和查用同一入口，才测得出内容漂移而不是提示语差异。
    """
    from sopcontrol.project import check_projections, write_all_projections

    work = _managed(tmp_path)
    written = write_all_projections(work)
    text = (work / "AGENTS.md").read_text(encoding="utf-8")
    assert "控制成熟度" in text
    assert "sopctl bootstrap" in text
    assert any(p.name == "AGENTS.md" for p in written)
    # 写完立刻查必须一致，否则 check 会报永久漂移
    assert all(r["status"] == "ok" for r in check_projections(work))


def test_projection_refreshes_when_level_changes(tmp_path):
    """等级变化会让投影过期 → project check 报 stale，提示重新投影。

    这是成熟度进投影后的代价，也是它有用的证据：如果等级变了投影仍报 ok，
    说明那一节其实没在反映真实状态。
    """
    from sopcontrol.project import check_projections, write_all_projections

    work = _managed(tmp_path)
    write_all_projections(work)
    assert main(["test-command", str(work), "--set", "pytest -q"]) == 0
    reports = {r["path"]: r for r in check_projections(work)}
    assert reports["AGENTS.md"]["status"] == "stale"


def test_guard_ids_in_orders_are_real(tmp_path):
    """秩序2 依赖的 guard 名必须是拦截器真的声明过的（防写死幻觉 id）。"""
    assert GUARD_PUSH_GATE in GUARD_IDS


def test_constitution_roundtrip(tmp_path):
    """save/load 对称，且落盘文件写清了「不是硬门」。"""
    work = _greenfield(tmp_path)
    main(["init", str(work)])
    candidates = scan_constitution(work)
    path = save_constitution(work, candidates)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "proposed" in raw["note"] and "硬门" in raw["note"]
    assert [c["candidate_id"] for c in load_constitution(work)] == [
        c["candidate_id"] for c in candidates
    ]

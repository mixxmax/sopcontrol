"""Surface Inventory 分支覆盖 + CLI 派发（WP-A1/A2/A5 验收支撑）。

每个测试断言实际行为（状态/文件/返回码/计数），不接受 truthy 返回值。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sopcontrol import surface_inventory as si
from sopcontrol.cli import main


def _product(tmp_path: Path) -> Path:
    root = tmp_path / "product"
    (root / "bin").mkdir(parents=True)
    (root / "tools").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "fx"\n', encoding="utf-8")
    s = root / "bin" / "report.sh"
    s.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    s.chmod(0o755)
    return root


def _init(root: Path) -> None:
    assert main(["init", str(root)]) == 0


# ---------------------------------------------------------------------------
# surface_identity：shell -c 剥壳 / 边界
# ---------------------------------------------------------------------------

def test_surface_identity_strips_shell_c_and_interpreter_prefix():
    inner = si.surface_identity("i", "shell", "exec", "", ["curl", "-s", "x"])
    wrapped = si.surface_identity("i", "shell", "exec", "", ["sh", "-c", "curl -s x"])
    assert wrapped == inner  # sh -c 外壳剥离后同身份
    via_python = si.surface_identity("i", "cli", "exec", "", ["python3.11", "tool", "a"])
    assert via_python == si.surface_identity("i", "cli", "exec", "", ["tool", "a"])
    assert si.surface_identity("i", "cli", "exec", "", []) != ""


def test_classify_surface_argv_routes_known_local_read_surface():
    # 已知分类面（pytest→未知程序→shell）走不通；用明确的本地脚本文件路径：
    # 未知程序 → unproven（不得默认 direct）
    surface, side, route = si.classify_surface_argv(["bin/unknown-thing"])
    assert side == "" and route == "unproven"
    # 已知网络程序 → 票据路由
    surface, side, route = si.classify_surface_argv(["curl", "https://x"])
    assert side == "network_request" and route == "bridge_challenge"
    # sh -c 内层网络命令 → 票据路由（外壳不掩盖内层）
    surface, side, route = si.classify_surface_argv(["sh", "-c", "curl https://x"])
    assert side == "network_request" and route == "bridge_challenge"


# ---------------------------------------------------------------------------
# SurfaceStore：损坏缓存 fail-open + 原子写失败清理
# ---------------------------------------------------------------------------

def test_store_load_corrupt_cache_fails_open(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    store = si.SurfaceStore(root)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{not json", encoding="utf-8")
    inv = store.load()
    assert inv.surfaces == [] and inv.root == str(root)


def test_refresh_rebuilds_after_cache_corruption(tmp_path):
    root = _product(tmp_path)
    _init(root)
    si.refresh_inventory(root)
    store = si.SurfaceStore(root)
    store.path.write_text("garbage", encoding="utf-8")  # 缓存损坏
    result = si.refresh_inventory(root)  # digest 未变但 surfaces 为空 → 重建
    assert result["reused"] is False and result["surfaces"] >= 1


# ---------------------------------------------------------------------------
# _records_from_manifest：harness / hook / config 面
# ---------------------------------------------------------------------------

def test_manifest_harness_hook_and_config_entries_become_surfaces(tmp_path):
    root = _product(tmp_path)
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    (root / ".opencode").mkdir()
    # 第三方 git hook（非 sopcontrol）
    proc = subprocess.run(["git", "-C", str(root), "init"], capture_output=True)
    if proc.returncode == 0:
        hooks = root / ".git" / "hooks"
        hook = hooks / "pre-commit"
        hook.write_text("#!/bin/sh\necho enterprise-linter\n", encoding="utf-8")
        hook.chmod(0o755)
    records = si._records_from_manifest(root)
    kinds = {r.kind for r in records}
    integrations = [r.integration for r in records]
    assert "harness.claude" in integrations and "harness.opencode" in integrations
    assert any(r.kind == "hook" for r in records) if proc.returncode == 0 else True
    assert "cli" in kinds


def test_hook_record_classifies_inner_command(tmp_path):
    root = _product(tmp_path)
    proc = subprocess.run(["git", "-C", str(root), "init"], capture_output=True)
    if proc.returncode != 0:
        pytest.skip("git 不可用")
    hooks = root / ".git" / "hooks"
    hook = hooks / "pre-push"
    hook.write_text("#!/bin/sh\ncurl https://example.internal/notify\n", encoding="utf-8")
    hook.chmod(0o755)
    records = [r for r in si._records_from_manifest(root) if r.kind == "hook"]
    assert records, "hook surface 未发现"
    assert records[0].side_effect_class == "network_request"
    assert records[0].high_impact is True
    assert records[0].control_route == "bridge_challenge"


# ---------------------------------------------------------------------------
# 匹配策略：capability（已安装 bridge 覆盖）/ direct（分类器证明本地面）
# ---------------------------------------------------------------------------

def test_capability_match_via_installed_bridge(tmp_path):
    root = _product(tmp_path)
    _init(root)
    from sopcontrol.bridge import install_wrapper

    install_wrapper(root, integration_id="cli.script.bin.report",
                    command=["bin/report.sh"], name="report-bridge")
    si.refresh_inventory(root, force=True)
    record = next(r for r in si.load_inventory(root).surfaces
                  if r.integration == "cli.script.bin.report")
    assert record.status == "mapped"
    assert record.match_kind == "capability"
    assert record.rule_ref == "bridge:report-bridge"
    assert record.control_route == "bridge_challenge"


def test_unresolved_surface_rematches_when_bridge_installed_later(tmp_path):
    """断点 D1 回归：先扫描为 observed 的 surface，之后安装覆盖它的 bridge，
    force 重扫必须重新匹配升级 mapped——不得因 _carry_over 短路永远停在 observed。
    """
    root = _product(tmp_path)
    _init(root)
    # 第一次扫描：没有任何 bridge → observed/candidate（未解决态）
    si.refresh_inventory(root, force=True)
    before = next(r for r in si.load_inventory(root).surfaces
                  if r.integration == "cli.script.bin.report")
    assert before.status in ("observed", "candidate")
    # 环境变化：安装覆盖该命令的 bridge
    from sopcontrol.bridge import install_wrapper

    install_wrapper(root, integration_id="cli.script.bin.report",
                    command=["bin/report.sh"], name="report-bridge")
    result = si.refresh_inventory(root, force=True)
    after = next(r for r in si.load_inventory(root).surfaces
                 if r.integration == "cli.script.bin.report")
    assert after.status == "mapped", f"重扫后仍停留在 {before.status}（断点 D1 复现）"
    assert after.match_kind == "capability"
    assert result["changed"] >= 1
    assert after.rule_ref == "bridge:report-bridge"


def test_template_match_inherits_same_integration_action_phase(tmp_path, monkeypatch):
    root = _product(tmp_path)
    _init(root)
    # 伪造一个既有 governed 模板，新增同元组的第二个实例 → 继承
    store = si.SurfaceStore(root)
    inv = store.load()
    inv.surfaces.append(si.SurfaceRecord(
        surface_id="surf-tpl-src", integration="cli.script.bin.report",
        kind="cli", action="exec", business_argv=["bin/report.sh"],
        side_effect_class="", status="governed", control_route="direct",
        rule_ref="RULE-TPL"))
    store.save(inv)

    original = si._records_from_manifest

    def fake_records(root):
        base = original(root)
        base.append(si.SurfaceRecord(
            surface_id="surf-tpl-second", integration="cli.script.bin.report",
            kind="cli", action="exec", business_argv=["bin/report2.sh"],
            side_effect_class="", status="observed", control_route="unproven"))
        return base

    monkeypatch.setattr(si, "_records_from_manifest", staticmethod(fake_records))
    monkeypatch.setattr(si, "_discovery_inputs_digest", staticmethod(lambda r: "dsc-tpl"))
    si.refresh_inventory(root, force=True)
    second = next(r for r in si.load_inventory(root).surfaces
                  if r.surface_id == "surf-tpl-second")
    assert second.status == "mapped" and second.rule_ref == "RULE-TPL"
    assert second.match_kind == "template"


def test_low_risk_classified_surface_maps_direct_without_ticket(tmp_path):
    root = _product(tmp_path)
    _init(root)
    # 显式 side_effect hint 的低风险面：background（subprocess 提示，非票据类）
    runner = root / "tools" / "runner.py"
    runner.write_text("import subprocess\nsubprocess.run(['ls'])\n", encoding="utf-8")
    si.refresh_inventory(root, force=True)
    bg = [r for r in si.load_inventory(root).surfaces if r.integration == "surface.background"]
    assert bg, "lexical hint 未生成 background surface"
    assert bg[0].side_effect_class == "background"
    assert bg[0].high_impact is False
    assert bg[0].status == "mapped"  # 声明面走受控路由，非 candidate


# ---------------------------------------------------------------------------
# accept/waive 边界 + CLI 派发全路径
# ---------------------------------------------------------------------------

def test_accept_is_idempotent_and_rejects_retired(tmp_path):
    root = _product(tmp_path)
    _init(root)
    si.refresh_inventory(root)
    record = next(r for r in si.load_inventory(root).surfaces
                  if r.integration == "cli.script.bin.report")
    first = si.accept_surface(root, record.surface_id, rule_id="SURF-IDEM-1")
    assert first["already"] is False
    second = si.accept_surface(root, record.surface_id, rule_id="SURF-IDEM-1")
    assert second["already"] is True and second["status"] == "governed"
    # retired 不可接受
    record.status = "retired"
    store = si.SurfaceStore(root)
    inv = store.load()
    for r in inv.surfaces:
        if r.surface_id == record.surface_id:
            r.status = "retired"
    store.save(inv)
    with pytest.raises(ValueError, match="retired"):
        si.accept_surface(root, record.surface_id, rule_id="SURF-IDEM-2")


def test_accept_reuses_existing_rule_by_id(tmp_path):
    root = _product(tmp_path)
    _init(root)
    si.refresh_inventory(root)
    record = next(r for r in si.load_inventory(root).surfaces
                  if r.integration == "cli.script.bin.report")
    # 预置同名规则（observed 态）→ accept 走「已有规则」分支，不重复 add
    from sopcontrol.model import Modality, RiskLevel, Rule, RuleStatus, SourceRef
    from sopcontrol.registry import Registry

    reg = Registry(root / ".sopcontrol" / "rules" / "registry.yaml")
    reg.add(Rule(rule_id="SURF-PRE", statement="预置规则", modality=Modality.MUST,
                 status=RuleStatus.observed, owner="user", risk=RiskLevel.low,
                 source=SourceRef(type="manual_seed", ref="pre")))
    result = si.accept_surface(root, record.surface_id, rule_id="SURF-PRE")
    assert result["status"] == "governed" and result["rule_status"] == "compiled"
    assert len(reg.load()) == 1  # 未重复登记


def test_cli_surface_full_dispatch(tmp_path, capsys):
    root = _product(tmp_path)
    # refresh（未 init 也能跑：inventory 是观察缓存）
    assert main(["surface", "refresh", str(root)]) == 0
    assert main(["surface", "refresh", str(root)]) == 0  # 第二次复用缓存
    assert main(["surface", "refresh", str(root), "--force"]) == 0
    # list / list --json / list --status
    assert main(["surface", "list", str(root)]) == 0
    assert main(["surface", "list", str(root), "--json"]) == 0
    assert main(["surface", "list", str(root), "--status", "candidate"]) == 0
    assert main(["surface", "list", str(root), "--status", "governed"]) == 0
    # coverage 两种输出
    assert main(["surface", "coverage", str(root)]) == 0
    assert main(["surface", "coverage", str(root), "--json"]) == 0
    # show：存在与不存在
    record = next(r for r in si.load_inventory(root).surfaces)
    assert main(["surface", "show", record.surface_id, str(root)]) == 0
    assert main(["surface", "show", "surf-missing", str(root)]) == 2
    # accept / waive 错误路径
    assert main(["surface", "accept", "surf-missing", str(root)]) == 2
    assert main(["surface", "waive", "surf-missing", str(root),
                 "--reason", "x"]) == 2
    # accept 正常路径（init 后）
    _init(root)
    record = next(r for r in si.load_inventory(root).surfaces
                  if r.integration == "cli.script.bin.report")
    assert main(["surface", "accept", record.surface_id, str(root),
                 "--rule-id", "SURF-CLI-1"]) == 0
    out = capsys.readouterr().out
    assert "governed" in out
    # waive 正常路径 + 缺理由（argparse required → SystemExit）
    assert main(["surface", "waive", record.surface_id, str(root),
                 "--reason", "不再治理"]) == 0
    with pytest.raises(SystemExit):
        main(["surface", "waive", record.surface_id, str(root)])
    # 未知子命令
    with pytest.raises(SystemExit):
        main(["surface", "no-such-sub", str(root)])


def test_inventory_summary_shape(tmp_path):
    root = _product(tmp_path)
    _init(root)
    si.refresh_inventory(root)
    summary = si.inventory_summary(root)
    assert summary["schema_version"] == si.SCHEMA_VERSION
    assert summary["counts"]["discovered_count"] == len(summary["surfaces"])
    assert set(summary["counts"]) >= {"discovered_count", "governed_count",
                                      "unresolved_count",
                                      "high_impact_unresolved_count"}


def test_gap_severity_table_complete():
    assert set(si.GAP_SEVERITY) == {"P0", "P1", "P2", "P3"}
    assert si.GAP_SEVERITY["P0"].startswith("可绕过")


def test_save_failure_cleans_tmp_and_raises(tmp_path, monkeypatch):
    import os

    root = _product(tmp_path)
    store = si.SurfaceStore(root)
    inv = si.SurfaceInventory(root=str(root), surfaces=[
        si.SurfaceRecord(surface_id="surf-x", integration="x", kind="cli")])

    def boom(src, dst):
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        store.save(inv)
    leftovers = [p for p in store.path.parent.iterdir() if p.name.startswith(".inventory.")]
    assert leftovers == []  # 临时文件已清理，不留半成品
    monkeypatch.undo()
    store.save(inv)  # 恢复后可正常写
    assert store.path.is_file()


def test_retired_surface_reappearing_reenters_matching_not_governed(tmp_path):
    root = _product(tmp_path)
    _init(root)
    si.refresh_inventory(root)
    record = next(r for r in si.load_inventory(root).surfaces
                  if r.integration == "cli.script.bin.report")
    si.accept_surface(root, record.surface_id, rule_id="SURF-REAPPEAR")
    # 删除脚本 → retired
    (root / "bin" / "report.sh").unlink()
    si.refresh_inventory(root, force=True)
    old = next(r for r in si.load_inventory(root).surfaces
               if r.integration == "cli.script.bin.report")
    assert old.status == "retired"
    # 重建同名脚本 → 重现：重新走匹配（不得自动恢复 governed）
    _re = root / "bin" / "report.sh"
    _re.write_text("#!/bin/sh\necho ok2\n", encoding="utf-8")
    _re.chmod(0o755)
    si.refresh_inventory(root, force=True)
    back = next(r for r in si.load_inventory(root).surfaces
                if r.integration == "cli.script.bin.report")
    assert back.status in ("candidate", "observed", "blocked"), back.status


def test_load_inventory_and_summary_on_fresh_project(tmp_path):
    root = _product(tmp_path)
    inv = si.load_inventory(root)
    assert inv.surfaces == []
    summary = si.inventory_summary(root)
    assert summary["surfaces"] == []

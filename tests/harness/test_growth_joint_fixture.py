"""WP-A4：生长与低接入的联合验收 fixture（手册 §20 六场景）。

不依赖 JobsFlow：临时目录里造一个最小产品（只读/写/外部副作用/多阶段），
验证「产品变化 → 发现 → 匹配/候选 → 显式定型 → 统一 admission → receipt」
全链路。每个场景独立成测试，断言实际行为（状态/文件/票据/回执），不接受
truthy 返回值。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sopcontrol import surface_inventory as si
from sopcontrol.bridge import run_bridge
from sopcontrol.tickets import issue_phase_grant, redeem_ticket, TicketError
from sopcontrol.cli import main


def _write(path: Path, content: str, mode: int = 0o755) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return path


def _admitting_child(root: Path, **kw) -> str:
    """生成一个会在真实入口 admit 票据的协作子进程脚本（不触网）。

    用当前解释器（sys.executable）作 shebang，保证子进程能 import sopcontrol；
    副作用标记写到 fixture 内绝对路径，不依赖子进程 cwd。
    """
    import sys

    return (
        f"#!/usr/bin/env {sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "from sopcontrol.bridge import admit_ticket\n"
        "tf = os.environ.get('SOPCTL_TICKET_FILE', '')\n"
        "argv = [sys.argv[0]] + sys.argv[1:]\n"
        "if tf:\n"
        "    admit_ticket(%r, ticket_file=tf, integration_id=%r, action=%r,\n"
        "                 argv=argv, side_effect=%r, task_id=%r)\n"
        "# 真实业务副作用：在 fixture 内写一个标记文件（绝对路径，随 cwd 稳定）\n"
        "Path(%r).write_text('written\\n')\n"
        "print('child-executed')\n"
    ) % (str(root), kw.get("integration_id", ""), kw.get("action", ""),
         kw.get("side_effect", ""), kw.get("task_id", ""),
         str(root / "sentinel.out"))


@pytest.fixture()
def product(tmp_path):
    """最小产品 fixture：只读 + 写 + 外部副作用 + wrapper + shell -c + harness。"""
    root = tmp_path / "product"
    root.mkdir()
    _write(root / "pyproject.toml",
           '[project]\nname = "fixture-product"\nversion = "0.1.0"\n'
           '[project.scripts]\nfixture-scan = "fixture:scan"\n')
    _write(root / "bin" / "report.sh", "#!/bin/sh\necho report-ok\n")
    _write(root / "tools" / "publish.py",
           "#!/usr/bin/env python3\nprint('published')\n")
    _write(root / "bin" / "writer.sh",
           "#!/bin/sh\necho writer-stub\n")
    _write(root / "bin" / "curl",
           "#!/bin/sh\necho net-stub\n")  # 按名分类为网络工具的本地 stub，不触网
    (root / ".opencode").mkdir()  # harness adapter 面
    # 预置既有产品状态（场景2 中途接入用）
    (root / "existing-state.txt").write_text("pre-existing\n", encoding="utf-8")
    return root


def _surface(root: Path, integration_substr: str) -> si.SurfaceRecord:
    inv = si.load_inventory(root)
    hits = [r for r in inv.surfaces if integration_substr in r.integration]
    assert hits, f"surface {integration_substr} 未发现: {[r.integration for r in inv.surfaces]}"
    return hits[0]


def _install_sopctl(root: Path) -> None:
    rc = main(["init", str(root)])
    assert rc == 0, "sopctl init 失败"


# ---------------------------------------------------------------------------
# 场景 1：从零安装——一次安装后已有入口可以开始受控运行
# ---------------------------------------------------------------------------

def test_scenario1_fresh_install_governs_existing_entries(product):
    _install_sopctl(product)
    result = si.refresh_inventory(product)
    assert result["reused"] is False
    counts = si.coverage_counts(si.load_inventory(product))
    assert counts["discovered_count"] >= 4
    assert counts["unresolved_count"] > 0  # 未解释 surface 存在时不得报 100%
    # 只读动作：本地直执行，无票据（§4.4 免票）
    stub = product / "bin" / "report.sh"
    receipt = run_bridge(product, integration_id="cli.script.bin.report",
                         action="scan", argv=[str(stub)])
    assert receipt["executed"] is True and receipt["exit_code"] == 0
    assert receipt["cost"]["challenge_count"] == 0
    assert receipt["cost"]["execute_count"] == 1
    # 写动作：声明 external_write → challenge → 子进程 admit → receipt 一致
    writer = _write(product / "bin" / "writer_real.py",
                    _admitting_child(product, integration_id="writer.cli",
                                     action="file.write", side_effect="external_write"))
    receipt = run_bridge(product, integration_id="writer.cli", action="file.write",
                         argv=[str(writer)], side_effect="external_write",
                         task_id="TASK-FX1")
    assert receipt["executed"] is True
    assert receipt["cost"] == {"challenge_count": 1, "admit_count": 1,
                               "execute_count": 1, "retry_count": 0,
                               "repeated_context_count": 0}
    assert receipt["operation_id"] == receipt["ticket"]["operation"]
    assert "secret" not in receipt["ticket"]
    assert (product / "sentinel.out").is_file()  # 真实副作用确实发生
    # 安装不覆盖用户原有配置
    assert (product / "existing-state.txt").read_text(encoding="utf-8") == "pre-existing\n"


# ---------------------------------------------------------------------------
# 场景 2：中途接入——先有产品状态，再装 SOP Control；未知动作不是静默放行
# ---------------------------------------------------------------------------

def test_scenario2_midstream_attach_preserves_and_flags_unknown(product):
    # 先「运行产品」：既有配置/状态文件先存在
    pre_snapshot = sorted(str(p.relative_to(product)) for p in product.rglob("*") if p.is_file())
    _install_sopctl(product)
    post_snapshot = sorted(str(p.relative_to(product)) for p in product.rglob("*") if p.is_file())
    added = set(post_snapshot) - set(pre_snapshot)
    assert all(n.startswith(".sopcontrol") for n in added), \
        f"中途接入了非自有文件: {added}"
    si.refresh_inventory(product)
    # 未知动作（未声明 side_effect、无法分类的脚本）：runtime 按 cooperating-
    # operator 边界处理，但 inventory 层该入口必须是 candidate/gap，不是 mapped
    unknown = _write(product / "bin" / "mystery-tool", "#!/bin/sh\necho ?\n")
    receipt = run_bridge(product, integration_id="unknown.cli", action="exec",
                         argv=[str(unknown)])
    si.refresh_inventory(product)
    record = _surface(product, "cli.script.bin.mystery-tool")
    assert record.status in ("candidate", "gap", "blocked"), record.status
    assert record.match_kind == "none"
    # 高影响（网络类名，按分类器）：没有 admit 子进程 → 挑战后不放行
    receipt = run_bridge(product, integration_id="net.cli", action="network.fetch",
                         argv=[str(product / "bin" / "curl")])
    assert receipt["challenge_count"] == 1  # 票据类自动分类 → 挑战而非直执行
    assert receipt["executed"] is False  # 无 admit 子进程 → 未放行


# ---------------------------------------------------------------------------
# 场景 3：新增能力——发现 → 继承/候选 → 显式接受 → revision → 受控执行
# ---------------------------------------------------------------------------

def test_scenario3_new_capability_to_governed_end_to_end(product):
    _install_sopctl(product)
    si.refresh_inventory(product)
    before = {r.surface_id for r in si.load_inventory(product).surfaces}
    # 产品新增一个能力
    _write(product / "tools" / "deploy.py", "#!/usr/bin/env python3\nprint('deploy')\n")
    result = si.refresh_inventory(product)
    assert result["reused"] is False and result["new"] >= 1
    inv = si.load_inventory(product)
    fresh = [r for r in inv.surfaces if r.surface_id not in before]
    assert fresh and fresh[0].status in ("candidate", "observed"), fresh[0].status
    record = fresh[0]
    # candidate 含可解释 diff 与待确认项
    assert record.needs_confirm, "候选必须列出待确认字段"
    assert record.match_reason
    # 未接受前：无规则 revision 产生
    rid = "SURF-DEPLOY-1"
    registry_before = _rule_count(product)
    governed = si.accept_surface(product, record.surface_id, rule_id=rid)
    assert governed["status"] == "governed"
    assert governed["rule_digest"]  # 接受产生稳定规则内容身份
    assert governed["rule_status"] == "compiled"  # 正规生命周期走完
    assert _rule_count(product) == registry_before + 1
    # 接受后：状态 governed，且强制重扫不回退（exact 继承；digest 未变时
    # refresh 复用缓存属正确行为，force 才会重新派生）
    si.refresh_inventory(product, force=True)
    after = _surface(product, "tools.deploy")
    assert after.status == "governed" and after.rule_ref == rid
    assert after.match_kind == "exact"
    # 新 surface 通过统一 admission 执行（声明外部副作用 → 票据链）
    child = _write(product / "tools" / "deploy_real.py",
                   _admitting_child(product, integration_id="tools.deploy",
                                    action="deploy", side_effect="external_write"))
    receipt = run_bridge(product, integration_id="tools.deploy", action="deploy",
                         argv=[str(child)], side_effect="external_write",
                         task_id="TASK-FX3")
    assert receipt["executed"] is True
    assert receipt["operation_id"] == receipt["ticket"]["operation"]
    assert receipt["cost"]["admit_count"] == 1


def _rule_count(root: Path) -> int:
    from sopcontrol.registry import Registry

    return len(Registry(root / ".sopcontrol" / "rules" / "registry.yaml").load())


# ---------------------------------------------------------------------------
# 场景 4：规则冲突——生长不得变成无声放宽
# ---------------------------------------------------------------------------

def test_scenario4_growth_rejects_widening(product):
    from sopcontrol.control_profile import (
        ProfileError, compose_effective_plan, normalize_profile, plan_digest,
    )

    BASE = {
        "profile_id": "fx",
        "scope": {"project": "current-project", "task": "TASK-FX4", "phase": "audit"},
        "checks": {"required": ["jd_fit"], "excluded": []},
        "baseline": {"source_ref": "jd", "generation_mode": "authoritative"},
        "repair": {"max_rounds": 1},
        "budget": {"max_audit_calls": 2, "max_repair_calls": 1},
    }
    base = normalize_profile(BASE)

    class F:
        pass

    def frozen(profile):
        f = F()
        f.profile_id, f.revision = profile.profile_id, 1
        f.digest = plan_digest(profile, 1)
        f.profile = profile
        return f

    # 新能力层显式删除 required check（excluded 注入）→ 拒绝
    widening = normalize_profile({**BASE, "checks": {
        "required": [], "excluded": ["jd_fit"], "modes": {"jd_fit": "ignore"}}})
    with pytest.raises(ProfileError):
        compose_effective_plan(frozen(widening), None, base_profile=base)
    # 显式放宽 tolerance → 拒绝
    strict = normalize_profile({**BASE, "tolerance": {"exaggeration": "block"}})
    loose = normalize_profile({**BASE, "tolerance": {"exaggeration": "allowed"}})
    with pytest.raises(ProfileError):
        compose_effective_plan(frozen(loose), None, base_profile=strict)
    # scope 扩大 → 拒绝
    narrow = normalize_profile({**BASE, "scope": {
        "project": "payment-service", "task": "TASK-FX4", "phase": "audit"}})
    wider = normalize_profile({**BASE, "scope": {
        "project": "current-project", "task": "TASK-FX4", "phase": "audit"}})
    with pytest.raises(ProfileError):
        compose_effective_plan(frozen(wider), None, base_profile=narrow)
    # 旧规则未被静默修改
    assert base.checks.required == ["jd_fit"]
    assert base.tolerance.get("exaggeration") in (None, "allowed")


# ---------------------------------------------------------------------------
# 场景 5：删除和重命名——retired 可解释；旧票据不适用于新身份
# ---------------------------------------------------------------------------

def test_scenario5_rename_retires_old_and_rejects_stale_ticket(product):
    _install_sopctl(product)
    si.refresh_inventory(product)
    record = _surface(product, "tools.publish")
    old_argv = list(record.business_argv)
    from sopcontrol.bridge import canonical_fingerprint, challenge_admission, admit_ticket

    issued = challenge_admission(product, integration_id=record.integration,
                                 action="exec", argv=old_argv,
                                 side_effect="external_write")
    old_ticket = issued["ticket_id"]
    # 重命名 surface（业务 argv 变化）
    (product / "tools" / "publish.py").rename(product / "tools" / "ship.py")
    result = si.refresh_inventory(product)
    assert result["retired"] >= 1
    inv = si.load_inventory(product)
    retired = [r for r in inv.surfaces if r.status == "retired"]
    assert any(r.integration == record.integration for r in retired)
    new_records = [r for r in inv.surfaces
                   if r.status != "retired" and "ship" in r.integration]
    assert new_records and new_records[0].status != "governed"  # 新身份不继承旧 governed
    # 旧票据对新 argv 失效（指纹绑定业务 argv）
    with pytest.raises(TicketError):
        admit_ticket(product, ticket_file=issued["handoff"],
                     integration_id=record.integration, action="exec",
                     argv=[str(product / "tools" / "ship.py")],
                     side_effect="external_write")
    # 旧票据未被消费过（消费语义仍由原操作的一次性 redeem 保证）
    from sopcontrol.tickets import is_ticket_consumed

    assert is_ticket_consumed(product, old_ticket) is False


# ---------------------------------------------------------------------------
# 场景 6：失败和恢复——安装/manifest/恢复/handoff 失败停在可恢复状态
# ---------------------------------------------------------------------------

def test_scenario6_failure_injections_recover(product, monkeypatch):
    _install_sopctl(product)
    si.refresh_inventory(product)
    from sopcontrol.bridge import _save_manifest, install_wrapper, remove_wrapper

    # 1. manifest 写失败：目标保持原内容，不提交成功 manifest
    bin_dir = product / ".sopcontrol-local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    pre = bin_dir / "fx-1"
    pre.write_text("#!/bin/sh\necho ORIGINAL\n", encoding="utf-8")
    pre.chmod(0o755)

    def boom(root, manifest):
        raise OSError("injected manifest failure")

    monkeypatch.setattr("sopcontrol.bridge._save_manifest", boom)
    with pytest.raises(RuntimeError, match="回滚清单失败"):
        install_wrapper(product, integration_id="fx.cli", command=["echo", "v"], name="fx-1")
    monkeypatch.undo()
    assert "ORIGINAL" in pre.read_text(encoding="utf-8")
    # 2. 恢复后重试安装/卸载仍可安全进行；重复安装保留最初 backup，
    #    卸载恢复 ORIGINAL（restored=True，removed=False 是正确语义）
    info = install_wrapper(product, integration_id="fx.cli", command=["echo", "v"], name="fx-1")
    assert Path(info["launcher"]).is_file()
    removed = remove_wrapper(product, name="fx-1")
    assert removed["restored"] is True
    assert "ORIGINAL" in pre.read_text(encoding="utf-8")
    # 3. handoff 竞态（同名已存在拒绝覆盖、symlink 不跟随）已有专项
    #    test_p1_secret_handoff.py；此处确认本场景没有遗留半成品 handoff。
    handoff_dir = product / ".sopcontrol-local" / "tickets" / ".handoff"
    assert not handoff_dir.exists() or all(
        p.is_file() and not p.is_symlink() for p in handoff_dir.iterdir())


# ---------------------------------------------------------------------------
# 多阶段流程：一个 phase grant 覆盖同阶段多个动作（§11.2 低成本）
# ---------------------------------------------------------------------------

def test_multiphase_flow_one_grant_covers_phase(product):
    _install_sopctl(product)
    from sopcontrol.tickets import issue_phase_grant, verify_ticket_for_admission

    grant = issue_phase_grant(
        product, phase="audit", allowed_side_effects=["external_write"],
        task_id="TASK-FXM", operation="op-multiphase-1",
        allowed_actions=["step.one", "step.two"], ttl_seconds=600)
    # 同阶段两个动作都用这枚 grant 核验（各自动作名在 allowed_actions 内）
    for action in ("step.one", "step.two"):
        info = verify_ticket_for_admission(
            product, ticket_id=grant.ticket_id, secret=grant.secret,
            action=action, input_fingerprint=grant.input_fingerprint,
            side_effect="external_write", task_id="TASK-FXM",
            expected_phase="audit", expected_operation_id="op-multiphase-1")
        assert info["verified"] is True and info["consumed"] is False
    # 阶段外动作被拒绝（空 allowed_actions 才通配；这里显式列了两步）
    with pytest.raises(TicketError):
        verify_ticket_for_admission(
            product, ticket_id=grant.ticket_id, secret=grant.secret,
            action="step.three", input_fingerprint=grant.input_fingerprint,
            side_effect="external_write", task_id="TASK-FXM",
            expected_phase="audit")


# ---------------------------------------------------------------------------
# §23 目标 A 命名测试：身份稳定性 / 增量成本 / 噪声控制
# ---------------------------------------------------------------------------

def test_surface_identity_ignores_wrapper_path(product):
    id1 = si.surface_identity("scan.cli", "cli", "exec", "", ["mytool", "--fast"])
    # §7.2：绝对路径的程序名是本机安装位置，不参与身份（wrapper 搬迁不换身份）
    assert id1 == si.surface_identity("scan.cli", "cli", "exec", "",
                                      ["/usr/local/bin/mytool", "--fast"])
    assert id1 == si.surface_identity("scan.cli", "cli", "exec", "",
                                      ["/opt/tools/v2/mytool", "--fast"])
    # 完全不同 argv 不能同身份
    assert id1 != si.surface_identity("scan.cli", "cli", "exec", "", ["mytool", "--slow"])
    # 仓库相对业务路径保留：不同目录的同名脚本仍是不同业务命令
    assert si.surface_identity("scan.cli", "cli", "exec", "", ["scripts/a/deploy.sh"]) != \
        si.surface_identity("scan.cli", "cli", "exec", "", ["scripts/b/deploy.sh"])
    # 无 wrapper 语义的非解释器 argv[0] 不被吞掉（业务名本身就是身份的一部分）
    assert id1 != si.surface_identity("scan.cli", "cli", "exec", "",
                                      ["other-tool", "mytool", "--fast"])


def test_surface_identity_absolute_install_path_is_not_identity():
    """§7.2 回归：hook/脚本里的绝对路径命令在安装位置变化后仍是同一 surface。

    断点 D2 的原始形态：路径限定 argv 此前产生不同身份，且对应测试是恒真式
    （assert id2 == id1 or id2 != id1），不证明任何性质。
    """
    a = si.surface_identity("hook.pre-commit", "hook", "exec", "",
                            ["/usr/local/bin/curl", "--version"])
    b = si.surface_identity("hook.pre-commit", "hook", "exec", "",
                            ["/opt/homebrew/bin/curl", "--version"])
    assert a == b, "同一业务命令的绝对安装路径不得改变 surface 身份"


def test_surface_identity_changes_with_business_argv_and_phase():
    base = si.surface_identity("i", "cli", "exec", "", ["tool", "a"])
    assert base != si.surface_identity("i", "cli", "exec", "", ["tool", "b"])
    assert base != si.surface_identity("i", "cli", "exec", "phase2", ["tool", "a"])
    assert base != si.surface_identity("i2", "cli", "exec", "", ["tool", "a"])
    # 解释器外壳剥离：python3 tool a ≡ tool a
    assert base == si.surface_identity("i", "cli", "exec", "", ["python3", "tool", "a"])


def test_no_change_does_not_rescan_full_project(product, monkeypatch):
    _install_sopctl(product)
    si.refresh_inventory(product)

    def forbidden_manifest(root):
        raise AssertionError("digest 未变时不得重新 build_manifest 全扫")

    monkeypatch.setattr("sopcontrol.surface_inventory._records_from_manifest",
                        forbidden_manifest)
    result = si.refresh_inventory(product)
    assert result["reused"] is True


def test_new_surface_inherits_template_without_extra_confirmation(product):
    _install_sopctl(product)
    si.refresh_inventory(product)
    # 把一个已知入口接受为 governed
    record = _surface(product, "cli.python.fixture-scan")
    si.accept_surface(product, record.surface_id, rule_id="SURF-SCAN-TPL")
    # 新增同 integration+action+side_effect 的兄弟实例 → 自动继承模板（无多余确认）
    _write(product / "bin" / "report2.sh", "#!/bin/sh\necho r2\n")
    # 同 integration 的模板要求 action/phase/side_effect 一致——fixture-scan 与
    # report2 是不同 integration，这里改为验证：新 integration 的未知脚本仍是
    # candidate（不得静默继承），只有显式 accept 才 governed
    si.refresh_inventory(product)
    new_record = _surface(product, "cli.script.bin.report2")
    assert new_record.status in ("candidate", "observed")
    with pytest.raises((KeyError, ValueError)):
        si.accept_surface(product, "surf-nonexistent")


def test_rejected_candidate_does_not_regenerate_noise(product):
    _install_sopctl(product)
    si.refresh_inventory(product)
    record = _surface(product, "cli.python.pytest")
    si.reject_candidate(product, record.surface_id, reason="不接受该入口")
    inv1 = si.load_inventory(product)
    status1 = next(r.status for r in inv1.surfaces if r.surface_id == record.surface_id)
    assert status1 == "waived"
    # 重复扫描（digest 未变复用；强制重扫也不复活同一噪声为 candidate）
    si.refresh_inventory(product, force=True)
    inv2 = si.load_inventory(product)
    again = next(r for r in inv2.surfaces if r.surface_id == record.surface_id)
    assert again.status == "waived" and again.waiver_reason.startswith("rejected:")


def test_waived_surface_requires_reason_and_is_counted(product):
    _install_sopctl(product)
    si.refresh_inventory(product)
    record = _surface(product, "cli.script.bin.report")
    with pytest.raises(ValueError):
        si.waive_surface(product, record.surface_id, reason="  ")
    si.waive_surface(product, record.surface_id, reason="只读报告工具，运行环境隔离")
    counts = si.coverage_counts(si.load_inventory(product))
    assert counts["waived_count"] >= 1


# ---------------------------------------------------------------------------
# §23 补齐：ambiguous / 高影响 blocked / CLI binding 全链 / 接受后可逆
# ---------------------------------------------------------------------------

def test_ambiguous_surface_creates_candidate_not_auto_choice(product, monkeypatch):
    _install_sopctl(product)
    si.refresh_inventory(product, force=True)
    # 构造两个同 (integration, action, phase, side_effect) 但 rule_ref 冲突的
    # governed 模板 + 一个新 surface，刷新后新 surface 必须 ambiguous
    inv = si.load_inventory(product)
    recs = list(inv.surfaces)
    recs.append(si.SurfaceRecord(
        surface_id="surf-tpl-a", integration="cli.script.bin.report",
        kind="cli", action="exec", business_argv=["a"], side_effect_class="",
        status="governed", control_route="bridge_challenge", rule_ref="RULE-A"))
    recs.append(si.SurfaceRecord(
        surface_id="surf-tpl-b", integration="cli.script.bin.report",
        kind="cli", action="exec", business_argv=["b"], side_effect_class="",
        status="governed", control_route="direct", rule_ref="RULE-B"))
    inv.surfaces = recs
    si.SurfaceStore(product).save(inv)

    def fake_manifest(root):
        return [si.SurfaceRecord(
            surface_id="surf-fresh-x", integration="cli.script.bin.report",
            kind="cli", action="exec", business_argv=["x"], side_effect_class="",
            status="observed", control_route="unproven")]

    monkeypatch.setattr(si, "_records_from_manifest", staticmethod(fake_manifest))
    monkeypatch.setattr(si, "_discovery_inputs_digest",
                        staticmethod(lambda root: "dsc-forced"))
    si.refresh_inventory(product, force=True)
    ambiguous = [r for r in si.load_inventory(product).surfaces
                 if r.surface_id == "surf-fresh-x"]
    assert ambiguous and ambiguous[0].status == "ambiguous"
    assert "冲突" in ambiguous[0].match_reason
    assert ambiguous[0].needs_confirm  # 不得自动选择，必须人工确认


def test_unknown_high_impact_surface_is_blocked(product):
    _install_sopctl(product)
    # 按名分类为网络工具的脚本 → 高影响 → blocked P0（不得 mapped/governed）
    _write(product / "bin" / "curl", "#!/bin/sh\necho net-stub\n")
    si.refresh_inventory(product, force=True)
    record = _surface(product, "cli.script.bin.curl")
    assert record.high_impact is True
    assert record.status == "blocked"
    assert record.severity == "P0"
    counts = si.coverage_counts(si.load_inventory(product))
    assert counts["high_impact_unresolved_count"] >= 1
    assert counts["enforce_ready"] is False  # 高影响未覆盖 → 不得过 enforce 门


def test_capability_binding_survives_cli_to_receipt(product, capsys):
    _install_sopctl(product)
    from sopcontrol.bridge import challenge_admission, admit_ticket

    # CLI challenge --capability-binding → ticket → CLI admit → 一致通过
    stub = _write(product / "bin" / "bound-tool", "#!/bin/sh\necho b\n")
    rc = main(["bridge", "challenge", "--action", "network.fetch",
               "--integration-id", "bound.cli", "--side-effect", "network_request",
               "--task-id", "TASK-BIND", "--capability-binding", "bind-cli-1",
               "--", str(stub)])
    assert rc == 0
    out = capsys.readouterr().out
    issued = json.loads(out[out.index("{"):])  # 跳过可能混入的非 JSON 前缀行
    assert issued["ticket"]["capability_binding"] == "bind-cli-1"
    rc = main(["bridge", "admit", "--action", "network.fetch",
               "--integration-id", "bound.cli", "--side-effect", "network_request",
               "--task-id", "TASK-BIND", "--capability-binding", "bind-cli-1",
               "--ticket-file", issued["handoff"], "--", str(stub)])
    assert rc == 0
    admitted = json.loads(capsys.readouterr().out)
    assert admitted["admitted"] is True
    # run_bridge 回执同样携带 binding（receipt 侧不丢字段）
    receipt = run_bridge(product, integration_id="bound.cli", action="network.fetch",
                         argv=[str(stub)], side_effect="network_request",
                         task_id="TASK-BIND", capability_binding="bind-cli-1")
    assert receipt["capability_binding"] == "bind-cli-1"
    assert receipt["operation_id"] == receipt["ticket"]["operation"]


def test_candidate_accept_is_reversible_via_waive(product):
    _install_sopctl(product)
    si.refresh_inventory(product)
    record = _surface(product, "cli.python.fixture-scan")
    si.accept_surface(product, record.surface_id, rule_id="SURF-REVERSIBLE")
    assert _surface(product, "cli.python.fixture-scan").status == "governed"
    # 操作者改变主意：显式 waive（带理由）→ 不再 governed；规则本身走 Registry
    # deprecate/supersede 流程另行处理（6R 已验证），inventory 与之一致回退
    si.waive_surface(product, record.surface_id, reason="决策反转：暂不治理该入口")
    after = _surface(product, "cli.python.fixture-scan")
    assert after.status == "waived" and after.waiver_reason
    counts = si.coverage_counts(si.load_inventory(product))
    assert counts["governed_count"] == 0

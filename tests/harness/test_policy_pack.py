"""P2 切片 C：外部 Policy Pack + 版本化连接器包（数据-only）。"""
from __future__ import annotations

import sys

from sopcontrol.cli import main
from sopcontrol.policy_pack import PackError, load_pack, match_breakers, validate_pack

PACK_YAML = """\
format_version: "1"
name: jobsdb-waf
version: 1.2.0
surfaces: [network, browser]
breakers:
  - id: waf-block
    surface: network
    match: {host: jobsdb.internal}
    decision: deny
    reason: 内网 WAF 未放行
connectors:
  - name: jobsdb-scan
    version: 0.3.0
    kind: cli_bridge
    entry: wrappers/jobsdb_scan.py
"""


def _pack(tmp_path, text=PACK_YAML):
    d = tmp_path / "pack"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pack.yaml").write_text(text, encoding="utf-8")
    return d


def test_valid_pack_loads_and_matches(tmp_path):
    d = _pack(tmp_path)
    assert validate_pack(d) == []
    pack = load_pack(d)
    assert pack.name == "jobsdb-waf" and pack.version == "1.2.0"
    hits = match_breakers(pack, surface="network", attrs={"host": "jobsdb.internal/api"})
    assert [b.id for b in hits] == ["waf-block"] and hits[0].decision == "deny"
    assert match_breakers(pack, surface="network", attrs={"host": "example.com"}) == []
    assert match_breakers(pack, surface="browser", attrs={"host": "jobsdb.internal"}) == []


def test_invalid_packs_rejected_with_reasons(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    assert validate_pack(d) == ["缺少 pack.yaml"]
    bad = _pack(tmp_path / "b", PACK_YAML.replace("1.2.0", "tomorrow").replace(
        "decision: deny", "decision: incinerate"))
    errors = validate_pack(bad)
    assert any("x.y.z" in e for e in errors)
    assert any("ask/deny" in e for e in errors)


def test_loader_never_imports_pack_code(tmp_path):
    d = _pack(tmp_path)
    (d / "evil.py").write_text("raise RuntimeError('must never execute')\n", encoding="utf-8")
    before = set(sys.modules)
    pack = load_pack(d)
    assert pack.connectors[0].entry == "wrappers/jobsdb_scan.py"
    assert set(sys.modules) - before == set()


def test_cli_validate_and_show(tmp_path, capsys):
    d = _pack(tmp_path)
    assert main(["pack", "validate", str(d)]) == 0
    assert main(["pack", "show", str(d)]) == 0
    out = capsys.readouterr().out
    assert "jobsdb-waf" in out and "waf-block" in out
    bad = tmp_path / "bad"
    bad.mkdir()
    assert main(["pack", "validate", str(bad)]) == 2
    try:
        load_pack(bad)
    except PackError:
        pass
    else:
        raise AssertionError("expected PackError")


DENY_NETWORK_PACK = """\
format_version: "1"
name: corp-egress
version: 2.0.0
surfaces: [network]
breakers:
  - id: egress-deny
    surface: network
    match: {command: curl}
    decision: deny
    reason: 外发需走审批通道
connectors: []
"""

ASK_PACK = """\
format_version: "1"
name: corp-audit
version: 1.0.0
surfaces: [shell]
breakers:
  - id: shell-ask
    surface: shell
    match: {command: echo}
    decision: ask
    reason: 高敏操作需票据
connectors: []
"""


def test_bridge_enforces_deny_breaker(tmp_path):
    from sopcontrol.bridge import run_bridge

    d = tmp_path / "denypack"
    d.mkdir()
    (d / "pack.yaml").write_text(DENY_NETWORK_PACK, encoding="utf-8")
    receipt = run_bridge(tmp_path, integration_id="scan.cli", action="network.scan",
                         argv=["curl", "--version"], side_effect="network_request",
                         policy_pack=str(d))
    assert receipt["executed"] is False
    assert receipt["policy_decision"] == "deny:egress-deny"
    assert "egress-deny" in receipt["error"]
    # 无 pack 时同调用正常执行（对照组）
    clean = run_bridge(tmp_path, integration_id="scan.cli", action="network.scan",
                       argv=["curl", "--version"], side_effect="network_request")
    assert clean["executed"] is True


def test_bridge_ask_forces_ticket_flow(tmp_path):
    from sopcontrol.bridge import run_bridge

    d = tmp_path / "askpack"
    d.mkdir()
    (d / "pack.yaml").write_text(ASK_PACK, encoding="utf-8")
    # echo 只读本可免票；ask breaker 强制走票（shell 非票据类 → 按 ask 语义拒绝直行）
    receipt = run_bridge(tmp_path, integration_id="scan.cli", action="scan",
                         argv=["echo", "hi"], policy_pack=str(d))
    assert receipt["policy_decision"] == "ask:shell-ask"
    # shell 无票据类：ask 无法落票则拒绝（不静默放行）
    assert receipt["executed"] is False


def test_bridge_rejects_invalid_pack(tmp_path):
    from sopcontrol.bridge import run_bridge

    d = tmp_path / "badpack"
    d.mkdir()
    receipt = run_bridge(tmp_path, integration_id="scan.cli", action="scan",
                         argv=["echo", "hi"], policy_pack=str(d))
    assert receipt["executed"] is False
    assert "policy pack 非法" in receipt["error"]


def test_bridge_run_cli_policy_pack_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "denypack"
    d.mkdir()
    (d / "pack.yaml").write_text(DENY_NETWORK_PACK, encoding="utf-8")
    rc = main(["bridge", "run", "--action", "network.scan",
               "--integration-id", "scan.cli",
               "--side-effect", "network_request",
               "--policy-pack", str(d),
               "--", "curl", "--version"])
    assert rc == 1
    capsys.readouterr()

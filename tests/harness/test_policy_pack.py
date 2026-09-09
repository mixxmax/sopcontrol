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

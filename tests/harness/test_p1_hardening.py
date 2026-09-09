"""Regressions for P1/P2 review: ingest, glob discovery, redact, attach/detach."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sopcontrol.cli import main
from sopcontrol.coverage import control_coverage
from sopcontrol.runtime import redact_argv, redact_command_summary


def test_claude_hook_matcher_accepts_all_tools(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    (work / ".claude").mkdir()
    (work / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    assert main(["hook", "claude", str(work)]) == 0
    data = json.loads((work / ".claude" / "settings.json").read_text(encoding="utf-8"))
    matchers = [e.get("matcher") for e in data["hooks"]["PreToolUse"]]
    assert any(m in {".*", ".*"} or (isinstance(m, str) and "Read" in m) or m == ".*" for m in matchers)
    assert any(m == ".*" for m in matchers)


def test_opencode_plugin_forwards_unknown_tools(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    (work / ".opencode").mkdir()
    assert main(["hook", "opencode", str(work)]) == 0
    text = (work / ".opencode" / "plugins" / "sopcontrol.js").read_text(encoding="utf-8")
    assert 'tool_name: String(input.tool' in text or "tool_name: String(input.tool" in text
    assert "if (!payload) return" not in text


def test_static_network_discovery_via_rglob(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    (work / "client.py").write_text("import httpx\nhttpx.get('https://x')\n", encoding="utf-8")
    report = control_coverage(work)
    net = next(s for s in report.surfaces if s.surface == "network")
    assert net.state == "gap"
    assert "network_usage_detected" in (net.gap_reason or "")


def test_effect_surfaces_not_auto_observable(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    report = control_coverage(work)
    for name in ("network", "browser", "credential"):
        rec = next(s for s in report.surfaces if s.surface == name)
        assert rec.state in {"detected", "gap"}
        assert rec.state != "observable" or "usage_detected" in (rec.gap_reason or "")


def test_runtime_redacts_secrets_in_argv():
    red = redact_argv([
        "curl", "-H", "Authorization=Bearer secrettoken", "--token", "abc123", "https://x",
    ])
    joined = " ".join(red)
    assert "secrettoken" not in joined
    assert "abc123" not in joined
    assert "***" in joined
    assert "supersecret" not in redact_command_summary(["export", "API_KEY=supersecret", "run"])


def test_attach_skips_creating_claude_opencode_when_absent(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=work, check=True, timeout=30)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=work, check=True, timeout=30)
    subprocess.run(["git", "config", "user.name", "t"], cwd=work, check=True, timeout=30)
    assert main(["attach", str(work)]) == 0
    assert not (work / ".claude").exists()
    assert not (work / ".opencode").exists()


def test_detach_removes_claude_sopctl_hooks(tmp_path):
    work = tmp_path / "p"
    work.mkdir()
    (work / ".claude").mkdir()
    (work / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "other"},
            {"type": "command", "command": "python -m sopcontrol.cli harness-check"},
        ]}]}}),
        encoding="utf-8",
    )
    assert main(["init", str(work)]) == 0
    assert main(["detach", str(work), "--confirm"]) == 0
    data = json.loads((work / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = data["hooks"]["PreToolUse"]
    commands = [h.get("command") for e in hooks for h in e.get("hooks", [])]
    assert all("sopcontrol.cli" not in str(c) for c in commands)
    assert any("other" in str(c) for c in commands)

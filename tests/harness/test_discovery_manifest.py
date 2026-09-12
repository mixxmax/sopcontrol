"""T-0095：Integration Manifest + 最轻连接规划。"""
from __future__ import annotations

import subprocess
from pathlib import Path

from sopcontrol.attachment import plan_attachment
from sopcontrol.cli import main
from sopcontrol.discovery_manifest import (
    build_manifest,
    manifest_summary,
    plan_connections,
)


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True, timeout=30)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True, timeout=30)


def _fixture_project(work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    _git_init(work)
    (work / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n[project.scripts]\ndemoscan = "demo:scan"\n',
        encoding="utf-8")
    (work / "package.json").write_text('{"scripts": {"lint": "eslint ."}}',
                                       encoding="utf-8")
    (work / "Makefile").write_text("test:\n\tpytest -q\n", encoding="utf-8")
    bin_dir = work / "bin"
    bin_dir.mkdir()
    (bin_dir / "prod-scan").write_text("#!/bin/sh\necho scan\n", encoding="utf-8")
    (work / "client.py").write_text("import httpx\nhttpx.get('https://x')\n",
                                    encoding="utf-8")
    hooks = work / ".git" / "hooks"
    (hooks / "pre-commit").write_text("#!/bin/sh\necho third-party\n", encoding="utf-8")


def test_manifest_discovers_cli_config_scripts_and_hints(tmp_path):
    work = tmp_path / "p"
    _fixture_project(work)
    manifest = build_manifest(work)
    ids = {e.id for e in manifest.entries}
    assert "cli.python.demoscan" in ids
    assert "cli.python.pytest" in ids
    assert "cli.node.lint" in ids
    assert "cli.make.test" in ids
    assert "cli.script.bin.prod-scan" in ids
    assert "surface.network" in ids
    assert "hook.thirdparty.pre-commit" in ids
    assert manifest.is_git is True


def test_planner_picks_lightest_way(tmp_path):
    work = tmp_path / "p"
    _fixture_project(work)
    plans = {p.entry_id: p for p in plan_connections(build_manifest(work))}
    assert plans["cli.python.demoscan"].way == "bridge_candidate"
    assert plans["cli.python.demoscan"].safe_auto is True
    assert "bridge install" in plans["cli.python.demoscan"].next_command
    assert plans["hook.thirdparty.pre-commit"].way == "direct_install"
    assert plans["surface.network"].way == "scaffold_confirm"
    assert plans["surface.network"].safe_auto is False


def test_empty_dir_yields_no_fake_entries(tmp_path):
    work = tmp_path / "e"
    work.mkdir()
    manifest = build_manifest(work)
    assert manifest.entries == []
    assert manifest_summary(manifest, plan_connections(manifest))["entries"] == 0


def test_manifest_cli_and_attach_plan_reference(tmp_path, capsys):
    work = tmp_path / "p"
    _fixture_project(work)
    assert main(["manifest", str(work)]) == 0
    out = capsys.readouterr().out
    assert "cli.python.demoscan" in out and "bridge install" in out
    assert main(["manifest", "--json", str(work)]) == 0
    import json

    out = capsys.readouterr().out
    data = json.loads(out[out.index("{"):])
    assert data["manifest"]["schema_version"] == "1"
    plan = plan_attachment(work)
    assert any("discovery:" in n and "sopctl manifest" in n for n in plan.notes)

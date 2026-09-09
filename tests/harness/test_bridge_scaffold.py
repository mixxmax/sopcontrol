"""P2 切片 B：bridge install/remove/list 接线 + 三语言 scaffold 模板。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sopcontrol.bridge_scaffold import LANGS, install_scaffold, render_scaffold
from sopcontrol.cli import main


def test_render_all_langs_carry_bridge_run_and_exit_code():
    args = ["bridge", "run", "--action", "network.scan",
            "--integration-id", "scan.cli", "--", "product", "scan"]
    for lang in LANGS:
        text = render_scaffold(lang=lang, bridge_args=args)
        assert "bridge" in text and "run" in text
        assert "network.scan" in text and "scan.cli" in text
        assert "secret" not in text.lower()
    assert "sys.exit" in render_scaffold(
        lang="python", bridge_args=args)
    assert "process.exit" in render_scaffold(
        lang="node", bridge_args=args)
    sh = render_scaffold(lang="sh", bridge_args=args)
    assert "SOPCTL_BIN" in sh and sh.rstrip().endswith('"$@"')


def test_render_rejects_unknown_lang():
    with pytest.raises(ValueError):
        render_scaffold(lang="ruby", bridge_args=["bridge", "run"])


def test_cli_install_list_remove_roundtrip(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["bridge", "install", "--action", "network.scan",
                 "--integration-id", "scan.cli",
                 "--", "product", "scan"]) == 0
    launcher = tmp_path / ".sopcontrol-local" / "bin" / "scan-cli-bridge"
    assert launcher.exists() and launcher.stat().st_mode & 0o111
    capsys.readouterr()  # 丢弃 install 的 JSON 输出

    assert main(["bridge", "list", "--json", ]) == 0
    out = capsys.readouterr().out
    manifest = json.loads(out[out.index("{"):])
    assert "scan-cli-bridge" in manifest

    assert main(["bridge", "remove", "--name", "scan-cli-bridge"]) == 0
    assert not launcher.exists()
    capsys.readouterr()  # 丢弃 remove 的 JSON 输出
    assert main(["bridge", "list", "--json"]) == 0
    out = capsys.readouterr().out
    assert "scan-cli-bridge" not in json.loads(out[out.index("{"):])


def test_scaffold_python_node_files_and_manifest(tmp_path):
    for lang, suffix in (("python", ".py"), ("node", ".js")):
        installed = install_scaffold(
            tmp_path, name=f"scan-{lang}", lang=lang,
            integration_id="scan.cli", action="network.scan",
            command=["product", "scan"],
        )
        target = Path(installed["file"])
        assert target.suffix == suffix
        assert target.exists() and target.stat().st_mode & 0o111

    manifest = json.loads(
        (tmp_path / ".sopcontrol-local" / "bridge-rollback.json").read_text(encoding="utf-8"))
    assert set(manifest) == {"scan-python", "scan-node"}
    assert manifest["scan-python"]["lang"] == "python"

    from sopcontrol.bridge import remove_wrapper
    assert remove_wrapper(tmp_path, name="scan-python")["removed"] is True
    assert not (tmp_path / ".sopcontrol-local" / "bin" / "scan-python.py").exists()


def test_install_requires_command(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["bridge", "install", "--action", "network.scan",
                 "--integration-id", "scan.cli"]) == 2

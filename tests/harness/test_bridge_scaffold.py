"""P2 切片 B：bridge install/remove/list 接线 + 三语言 scaffold 模板。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sopcontrol.bridge_scaffold import LANGS, install_scaffold, render_scaffold
from sopcontrol.cli import main


def _render(lang, **kw):
    base = {"integration_id": "scan.cli", "action": "network.scan",
            "command": ["product", "scan"]}
    base.update(kw)
    return render_scaffold(lang=lang, **base)


def test_render_all_langs_admit_then_exec():
    for lang in LANGS:
        text = _render(lang, side_effect="network_request")
        assert "bridge" in text and "admit" in text
        assert "network.scan" in text and "scan.cli" in text
        assert "secret" not in text.lower()
    assert "sys.exit" in _render("python", side_effect="network_request")
    assert "process.exit" in _render("node", side_effect="network_request")
    sh = _render("sh", side_effect="network_request")
    assert "SOPCTL_BIN" in sh and "SOPCTL_TICKET_FILE" in sh
    assert sh.rstrip().endswith('"$@"')
    # 只读无票据类：直接 exec，不走 admit
    assert "admit" not in _render("sh")


def test_render_rejects_unknown_lang():
    with pytest.raises(ValueError):
        render_scaffold(lang="ruby", integration_id="x", action="a",
                        command=["echo"])


def test_render_rejects_empty_command():
    with pytest.raises(ValueError):
        render_scaffold(lang="sh", integration_id="x", action="a", command=[])


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


def test_installed_entry_standalone_admits_and_execs(tmp_path, monkeypatch):
    """已安装入口独立运行：challenge 自己 → admit 自己 → exec（真闭环）。"""
    import subprocess as _subprocess
    import sys as _sys
    from pathlib import Path as _Path

    pybin = _Path(_sys.executable)
    sopctl = pybin.parent / "sopctl"
    monkeypatch.setenv("SOPCTL_BIN",
                       str(sopctl) if sopctl.is_file() else f"{pybin} -m sopcontrol.cli")
    installed = install_scaffold(
        tmp_path, name="demo-entry", lang="sh",
        integration_id="demo.cli", action="network.scan",
        command=["echo"], side_effect="network_request",
    )
    proc = _subprocess.run([installed["file"], "hello-entry"],
                           capture_output=True, text=True, timeout=60,
                           cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr[-500:]
    assert "hello-entry" in proc.stdout


def test_installed_readonly_entry_direct_exec(tmp_path):
    import subprocess as _subprocess

    installed = install_scaffold(
        tmp_path, name="ro-entry", lang="sh",
        integration_id="demo.cli", action="scan", command=["echo"],
    )
    proc = _subprocess.run([installed["file"], "hi"], capture_output=True,
                           text=True, timeout=30)
    assert proc.returncode == 0 and "hi" in proc.stdout

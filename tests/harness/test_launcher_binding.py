"""T3：bound_launch 绑定解析（§9.6 可证明子集）。"""
from __future__ import annotations

from pathlib import Path

from sopcontrol.resolve_cli import bound_launch
from sopcontrol.upgrade import init_binding, save_binding


def _bind(project: Path, **kw) -> None:
    b = init_binding(project)
    for k, v in kw.items():
        setattr(b, k, v)
    save_binding(project, b)


def test_unbound_projects_keep_legacy_chain(tmp_path):
    r = bound_launch(tmp_path)
    assert r["ok"] is True and r["bound"] is False and r["argv"] is None


def test_corrupt_binding_fail_closed(tmp_path):
    d = tmp_path / ".sopcontrol-local"
    d.mkdir(parents=True)
    (d / "binding.yaml").write_text("{坏: [", encoding="utf-8")
    r = bound_launch(tmp_path)
    assert r["ok"] is False and "hint" in r


def test_outside_allowed_dir_refused(tmp_path):
    _bind(tmp_path, runtime_path="/etc/sopctl-evil", core_version="0.3.0")
    r = bound_launch(tmp_path)
    assert r["ok"] is False and "允许目录" in str(r["reason"])


def test_staged_binding_resolves_argv_env(tmp_path):
    import json
    staged = tmp_path / ".sopcontrol-local" / "runtimes" / "0.3.0"
    staged.mkdir(parents=True)
    (staged / "runtime-manifest.json").write_text(json.dumps(
        {"version": "0.3.0", "package_digest": "dg1"}), encoding="utf-8")
    _bind(tmp_path, runtime_path=str(staged), core_version="0.3.0",
          runtime_package_digest="dg1")
    r = bound_launch(tmp_path)
    assert r["ok"] is True and r["argv"][-2:] == ["-m", "sopcontrol.cli"]
    assert str(staged) in str(r["env"].get("PYTHONPATH", ""))


def test_digest_mismatch_refused(tmp_path):
    import json
    staged = tmp_path / ".sopcontrol-local" / "runtimes" / "0.3.0"
    staged.mkdir(parents=True)
    (staged / "runtime-manifest.json").write_text(json.dumps(
        {"version": "0.3.0", "package_digest": "OTHER"}), encoding="utf-8")
    _bind(tmp_path, runtime_path=str(staged), core_version="0.3.0",
          runtime_package_digest="dg1")
    r = bound_launch(tmp_path)
    assert r["ok"] is False and "摘要" in str(r["reason"])


def test_missing_package_refused(tmp_path):
    ghost = tmp_path / ".sopcontrol-local" / "runtimes" / "9.9.9"
    ghost.mkdir(parents=True)
    _bind(tmp_path, runtime_path=str(ghost), core_version="9.9.9")
    r = bound_launch(tmp_path)
    assert r["ok"] is False

"""Phase 6 种子：项目身份同根稳定、lock 后路径变更不改 id。"""
import shutil

from sopcontrol.cli import main
from sopcontrol.identity import (
    compute_project_id,
    ensure_identity,
    load_identity,
    set_identity_locked,
)


def test_identity_stable_for_same_root(tmp_path):
    a = ensure_identity(tmp_path)
    b = ensure_identity(tmp_path)
    assert a.project_id == b.project_id == compute_project_id(tmp_path)
    assert load_identity(tmp_path).project_id == a.project_id


def test_cli_init_writes_identity(tmp_path):
    assert main(["init", str(tmp_path)]) == 0
    assert main(["identity", "show", str(tmp_path)]) == 0
    ident = load_identity(tmp_path)
    assert ident is not None and ident.project_id.startswith("proj-")


def test_identity_export_import(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    ensure_identity(a)
    set_identity_locked(a, True)
    pid = load_identity(a).project_id
    bundle = tmp_path / "id.yaml"
    assert main(["identity", "export", str(a), "--out", str(bundle)]) == 0
    assert main(["identity", "import", str(b), "--file", str(bundle)]) == 0
    imported = load_identity(b)
    assert imported.project_id == pid and imported.locked is True


def test_locked_identity_survives_path_move(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    ensure_identity(a)
    set_identity_locked(a, True)
    locked_id = load_identity(a).project_id
    b.mkdir()
    shutil.copytree(a / ".sopcontrol", b / ".sopcontrol")
    moved = ensure_identity(b)
    assert moved.locked is True
    assert moved.project_id == locked_id
    assert moved.root == str(b.resolve())

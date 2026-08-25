"""Phase 6 种子：项目身份同根稳定、init/show 可查。"""
from sopcontrol.cli import main
from sopcontrol.identity import compute_project_id, ensure_identity, load_identity


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

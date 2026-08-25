"""垂直骨干役用：doctor --vertical 与 meta 排除后的自应用判定。"""
import shutil

from sopcontrol.cli import main


def test_doctor_vertical_requires_identity_and_hook(tmp_path):
    work = tmp_path / "work"
    shutil.copytree("corpus/fixtures/ci-deploy", work)
    # 无身份、无钩子 → --vertical 失败
    assert main(["doctor", str(work), "--vertical"]) == 1
    assert main(["identity", "init", str(work)]) == 0
    # 仍无 git hook
    assert main(["doctor", str(work), "--vertical"]) == 1

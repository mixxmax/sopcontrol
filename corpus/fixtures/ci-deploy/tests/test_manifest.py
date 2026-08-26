"""清单载入的回归——生产入口在 scripts/spec/manifest_loader.py。

这条测试与那个生产文件一起构成 test_helper_only 的负向对照第二域：消费者同时
存在于生产与测试路径，检测器必须沉默。若把嵌套 spec/ 判成测试，生产侧就空了，
本域会误报「只有测试 helper」。
"""

from spec.manifest_loader import load_deploy_manifest


def test_load_manifest():
    assert load_deploy_manifest('{"targets": ["prod"]}')["targets"] == ["prod"]

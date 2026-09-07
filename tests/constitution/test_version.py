"""发布版本元数据必须与导入时暴露的版本保持一致。"""
from importlib.metadata import version

import sopcontrol


def test_imported_version_matches_distribution_metadata():
    assert sopcontrol.__version__ == version("sopcontrol")

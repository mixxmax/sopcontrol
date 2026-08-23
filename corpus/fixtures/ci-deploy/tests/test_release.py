"""测试 helper 自造前置（手册 1.2 症状4/14.1 场景4：测试造出生产不存在的前置资源）。"""


def release_guard(artifact):
    """这个 guard 只存在于测试里——生产脚本从不调用它。"""
    return True


def test_release():
    assert release_guard({"pkg": 1}) is True

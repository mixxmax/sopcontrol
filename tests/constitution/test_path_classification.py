"""路径分类的双向断言（RESIDUAL_RISKS R2 的可回归部分）。

is_test_path 是整个吸收判定的地基：判错一个方向就漏报（测试 helper 冒充生产），
判错另一个方向就误报（真生产消费者被当成测试）。两种错误都会让人开始绕过控制器，
所以两个方向都要有断言，而不只是「测试文件识别得出来」。
"""
import pytest

from sopcontrol.context import is_production_path, is_test_path

# 必须识别为测试的路径。同置命名是 Go 的强制约定、JS/TS 的生态惯例——
# 只认 tests/ 目录会把这些回归文件读成生产代码，"有测试"于是被判成"无回归证据"。
TEST_PATHS = [
    "tests/test_gate.py",
    "tests/gate.test.ts",
    "src/limiter_test.go",
    "src/limiter.test.ts",
    "src/limiter.spec.tsx",
    "src/lim_test.rs",
    "src/foo_test.py",
    "conftest.py",
    "spec/models/user_spec.rb",  # 根级 spec/ 是 RSpec/Jasmine 的测试根
    "__tests__/gate.js",
]

# 必须识别为生产的路径。嵌套 spec/ 几乎都是 OpenAPI / JSON Schema 一类的生产包，
# 一律当测试就会把唯一的生产消费者判没，于是 test_helper_only 在正确代码上报警。
PRODUCTION_PATHS = [
    "src/checkout.py",
    "src/gate.ts",
    "src/spec/validator.py",
    "scripts/spec/manifest_loader.py",
    "src/specification.py",  # 前缀相同不等于同一个词
    "src/latest.py",
    "src/contest.py",
]


@pytest.mark.parametrize("relpath", TEST_PATHS)
def test_recognized_as_test(relpath):
    assert is_test_path(relpath), f"{relpath} 应判为测试路径"
    assert not is_production_path(relpath)


@pytest.mark.parametrize("relpath", PRODUCTION_PATHS)
def test_recognized_as_production(relpath):
    assert not is_test_path(relpath), f"{relpath} 应判为生产路径"
    assert is_production_path(relpath)

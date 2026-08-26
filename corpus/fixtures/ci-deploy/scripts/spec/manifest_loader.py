"""部署清单的 schema 载入——生产代码，住在 spec/ 包里（CI 域）。

与 shop-checkout/src/spec/validator.py 同一模式的第二域：嵌套 `spec/` 装的是
OpenAPI / JSON Schema 这类生产代码，不是测试根。一律当测试会让这里唯一的生产
消费者消失，于是 test_helper_only 在接线且有回归的正确代码上报警。
"""

import json


def load_deploy_manifest(raw: str) -> dict:
    """唯一的清单载入入口；发布链路只经此处。"""
    data = json.loads(raw)
    if "targets" not in data:
        raise ValueError("manifest 缺少 targets")
    return data

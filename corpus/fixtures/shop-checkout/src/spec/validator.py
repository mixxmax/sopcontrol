"""退款请求的形状校验——生产代码，住在 spec/ 包里。

`spec/` 这个目录名有两种用法：根级 `spec/` 是 RSpec/Jasmine 的测试根，嵌套的
`src/spec/` 基本都是 OpenAPI / JSON Schema 一类的**生产**代码。把嵌套 spec/ 一律
当测试，就会把这里的唯一生产消费者判没，于是「接了线也测了」被读成「只有测试
helper，生产还缺」——test_helper_only 在完全正确的代码上报警。
"""


def validate_refund_shape(req: dict) -> bool:
    """唯一的退款形状校验入口；生产链路只经此处。"""
    return isinstance(req.get("order_id"), str) and req.get("amount", 0) > 0

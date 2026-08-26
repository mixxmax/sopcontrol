"""通道注册表：唯一真源（state_in_parallel_files 第二域负向对照的写侧）。

只有本文件写 channel_registry，routing.py 只读。这正是规则要求的单一真源，
判成双处维护就是惩罚正确的分层。第一域对照见 healthy-billing/billing.py。
"""

channel_registry = {}


def register_channel(name, endpoint):
    channel_registry[name] = endpoint
    return {"name": name, "endpoint": endpoint}

"""发布审计日志（生产实现）。"""


def record_audit_entry(action, actor, sink):
    """每次发布动作都必须留一条审计记录。"""
    entry = {"action": action, "actor": actor}
    sink.append(entry)
    return entry

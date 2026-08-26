"""账单报表：只读上游状态，不维护副本。

这是"定义在一处、读取在别处"的正确分层。它长得很像 5.8 的双处维护——同一个
名字出现在两个文件里——区别只在这里没有任何写入。检测器要能分清这两者，否则
正确的分层就成了 gap。
"""

from billing import audit_field, invoice_state


def monthly_report():
    return {"invoices": dict(invoice_state), "note": audit_field}

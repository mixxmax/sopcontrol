"""灰度报表：只读 rollout_audit，构成跨文件的读写闭合。

审计字段的价值就在于被别的模块读取——写侧与读侧天然不在一个文件里。把已经有
读者的字段判成无人消费，等于要求把审计逻辑塞回业务文件才承认它被用了。
"""

from rollout import rollout_audit


def audit_trail():
    return list(rollout_audit)


def rollout_count():
    return len(rollout_audit)

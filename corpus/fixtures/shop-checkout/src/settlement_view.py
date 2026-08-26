"""结算视图：只读 settle_audit，构成读写闭合的读侧。

有了这一侧，「字段写出但从未读取」就不该报——审计字段的价值恰恰在于被下游
读取，把已经有读者的字段判成无人消费，是在催人删掉正在用的东西。
"""

from settlement import settle_audit


def last_settlement():
    return settle_audit or "none"

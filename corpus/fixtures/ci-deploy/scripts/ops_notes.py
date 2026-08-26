"""运维备注（comment_only_reference 的第二域负向对照）。

真引用在 rollback.py（`rollback(target)` 调用 `rollback_guard`），这里只是文档性
提及。把「另一个文件的注释里提到它」判成断口，等于惩罚写注释的人；这与漏报
同为错报。healthy-billing/dashboard.py 是同一模式的第一域对照。
"""


def oncall_checklist():
    # 回滚前先确认 rollback_guard 的白名单已同步（这一行是散文，不是引用）
    return ["确认变更单", "确认回滚路径", "确认值班交接"]

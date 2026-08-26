"""灰度发布域：审计轨迹的写侧（schema_field_unread 第二域负向对照）。

本文件只写 rollout_audit，从不读它；读取全在 rollout_report.py。这种「写在业务
路径、读在报表路径」是审计字段最常见的正确形态——检测器若只在写入者本文件里找
读取，就会把它判成「写出但从未读取」，催人删掉正在被下游消费的字段。
第一域对照见 shop-checkout/REFUND-011（settle_audit）。
"""

rollout_audit = ""


def start_rollout(service, percent):
    global rollout_audit
    rollout_audit = f"{service}@{percent}"
    return {"service": service, "percent": percent, "state": "rolling"}

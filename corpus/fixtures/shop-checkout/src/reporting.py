"""对账报表（并行维护现场：与 checkout 各自维护同一份状态副本）。"""

from checkout import ledger_status


def daily_report():
    return dict(ledger_status)


def mark_reconciled(order):
    """报表侧直接改写对账状态——这就是「双处维护」的现场。"""
    ledger_status[order] = "reconciled"

# 场景3：schema 字段只写不读
schema_extra_field = "v2"

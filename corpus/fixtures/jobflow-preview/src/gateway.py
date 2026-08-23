"""统一入表 gateway（新链：受控入口）。"""

preview_state = {}


def workflow_gateway(sheet, row, confirmed):
    """唯一合法入表入口：确认后才写。"""
    if not confirmed:
        raise ValueError("未确认，拒绝入表")
    preview_state["last"] = row
    sheet.append(row)

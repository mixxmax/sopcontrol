"""历史遗留脚本：不经受控入口直接写表（旧链仍存活）。"""


def direct_write(sheet, row):
    sheet.append(row)

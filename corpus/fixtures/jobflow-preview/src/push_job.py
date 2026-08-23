"""岗位入表入口（历史断口现场：直接写表，绕过预览确认环节）。"""


def push_job(sheet, row):
    """直接把岗位写入表内——预览确认的强制点在此路径上不存在。"""
    sheet.append(row)
    return len(sheet.rows)

"""运营看板：只在文字里提到 charge_gate，真正调用在 service.py。

这是 comment_only_reference 的负向对照：注释提及本身不是罪。真引用在别处时，
把「某文件的注释里提到它」判成断口，等于惩罚写文档的人。检测器要看全项目有
没有真引用，而不是逐文件问「这里是不是只有注释」。
"""


def render():
    # 扣费口径见 charge_gate（本模块不直接扣费，只展示）
    return {"view": "ops"}

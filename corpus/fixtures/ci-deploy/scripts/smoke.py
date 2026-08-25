"""生产冒烟探针——无对应测试引用（documented_rule_untested 第二域）。"""


def smoke_probe(target):
    return {"ok": True, "target": target}

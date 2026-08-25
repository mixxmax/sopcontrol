"""生产冒烟探针——无对应测试引用（documented_rule_untested 第二域）。"""


def smoke_probe(target):
    return {"ok": True, "target": target}

# 场景3：schema 字段只写不读
release_schema_field = 1

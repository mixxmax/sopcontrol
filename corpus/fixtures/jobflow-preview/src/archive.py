"""材料归档通道（生产实现）。"""


def archive_material(item, store):
    """把材料归档，返回归档后的记录。"""
    record = {"id": item["id"], "archived": True}
    store.append(record)
    return record

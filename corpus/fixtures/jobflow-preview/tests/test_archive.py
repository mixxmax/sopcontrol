"""归档回归：整条链路都打在替身上，从未接触 src/archive.py。"""
from unittest.mock import Mock


def test_archives_material():
    store = []
    channel = Mock()
    channel.archive_material.return_value = {"id": "job-1", "archived": True}
    record = channel.archive_material({"id": "job-1"}, store)
    assert record["archived"]

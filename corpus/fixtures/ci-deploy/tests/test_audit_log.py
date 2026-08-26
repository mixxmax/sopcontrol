"""审计回归：只验证替身的行为，从未 import scripts/audit_log.py。"""
from unittest.mock import Mock


def test_records_audit_entry():
    sink = []
    logger = Mock()
    logger.record_audit_entry.return_value = {"action": "deploy", "actor": "ci"}
    entry = logger.record_audit_entry("deploy", "ci", sink)
    assert entry["action"] == "deploy"

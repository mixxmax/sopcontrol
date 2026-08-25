"""go_scan：注释剥离；真实标识保留。"""
from plugins.sensors.go_scan import static_references


def test_go_strips_comments_keeps_idents():
    src = """
package main
// RegisterAuditHook should not count
func AdmitRequest() {}
"""
    refs = static_references(src)
    assert "AdmitRequest" in refs
    assert "RegisterAuditHook" not in refs

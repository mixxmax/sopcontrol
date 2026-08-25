"""rust_scan：注释剥离。"""
from plugins.sensors.rust_scan import static_references


def test_rust_strips_comments():
    src = """
// register_audit_hook should not count
pub fn admit_request() {}
"""
    refs = static_references(src)
    assert "admit_request" in refs
    assert "register_audit_hook" not in refs

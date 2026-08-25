"""js_scan：注释/字符串剥离；真实引用保留。"""
from plugins.sensors.js_scan import static_references, strip_comments_and_strings


def test_strips_line_and_block_comments():
    src = """
// audit_hook should not count
const x = 1; /* audit_hook inside block */
export function request_gate() { return true; }
"""
    refs = static_references(src)
    assert "request_gate" in refs
    assert "audit_hook" not in refs


def test_strips_string_literals():
    src = 'const msg = "please call audit_hook later";\nconst y = audit_hook;\n'
    refs = static_references(src)
    assert "audit_hook" in refs  # 真实标识符
    # 仅字符串出现时不命中
    only_str = 'const msg = "audit_hook";\n'
    assert "audit_hook" not in static_references(only_str)


def test_strip_preserves_newlines():
    text = "a\n// hide\nb\n"
    assert "\n" in strip_comments_and_strings(text)

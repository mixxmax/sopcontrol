"""ts_ast_scan 单元测试：AST 引用、import 归一、词法回退边界（go_ast 模板复制）。"""
from sopcontrol.context import ProjectContext
from plugins.sensors.ts_ast_scan import (
    TsAstScanSensor,
    imports,
    normalize_specifier,
    static_references,
    ts_import_closure,
)

GATE = '''
import { request_gate } from "./gate";
import vim from "vitest";
// ghost_only_marker 只在注释里出现
export function handleWrite(payload: Request) {
  const note = "string_only_marker 也不是引用";
  return request_gate(payload);
}
'''


def test_references_exclude_comments_and_strings():
    refs = static_references(GATE)  # 集合语义：同名只出现一次
    assert "request_gate" in refs and "handleWrite" in refs and "Request" in refs
    assert "ghost_only_marker" not in refs, "注释里的标识符不得成为引用"
    assert "string_only_marker" not in refs, "字符串里的标识符不得成为引用"


def test_imports_normalized_to_top_level_names():
    assert imports(GATE) == ["gate", "vitest"]


def test_normalize_specifier_strips_relative_and_extension():
    assert normalize_specifier("./gate") == "gate"
    assert normalize_specifier("../src/gate.ts") == "gate"
    assert normalize_specifier("@scope/pkg/inner.js") == "inner"
    assert normalize_specifier("") == ""


def test_unparseable_source_signals_none():
    assert static_references("function broken( {") == []
    assert imports("import { from \"unclosed") == []


def test_sensor_parseable_ts_never_falls_back_to_lexical(tmp_path):
    """解析成功的 .ts 不产词法证据——纯注释文件在词法层会产出假引用，
    恰好毁掉 comment_only_reference 模式（宁可沉默）。"""
    (tmp_path / "pure_comment.ts").write_text(
        "// request_gate 和 audit_hook 都只是注释\n", encoding="utf-8"
    )
    rows = TsAstScanSensor().observe(ProjectContext(tmp_path))
    assert rows == [], "解析成功的纯注释 .ts 不应产出任何证据"


def test_sensor_ts_emits_references_and_imports(tmp_path):
    (tmp_path / "gate.ts").write_text(
        'import { x } from "./dep";\nexport function gate() { return x; }\n',
        encoding="utf-8",
    )
    rows = TsAstScanSensor().observe(ProjectContext(tmp_path))
    kinds = sorted(r.kind for r in rows)
    assert kinds == ["ts_ast.imports", "ts_ast.references"]


def test_sensor_unparseable_ts_falls_back_to_lexical(tmp_path):
    (tmp_path / "broken.ts").write_text("function broken( {", encoding="utf-8")
    rows = TsAstScanSensor().observe(ProjectContext(tmp_path))
    assert [r.kind for r in rows] == ["js_scan.references"]


def test_sensor_js_family_stays_lexical(tmp_path):
    """.js 家族按设计永留词法层：kind 是 js_scan.references，grounding 依 kind 标 lexical。"""
    (tmp_path / "legacy.js").write_text(
        "export function legacy_gate(p) { return p; }\n", encoding="utf-8"
    )
    rows = TsAstScanSensor().observe(ProjectContext(tmp_path))
    assert [r.kind for r in rows] == ["js_scan.references"]
    assert rows[0].observer == "ts_ast_scan"


def test_ts_import_closure_reuses_python_machine():
    adjacency = {"src/client.ts": ["gate", "vitest"]}
    by_module = {"gate": ["src/gate.ts"], "client": ["src/client.ts"]}
    modules, files = ts_import_closure("src/client.ts", adjacency, by_module)
    assert "src/gate.ts" in files
    assert "vitest" in modules

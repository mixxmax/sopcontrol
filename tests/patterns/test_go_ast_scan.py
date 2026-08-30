"""go_ast_scan 单元测试：AST 引用、包/import 提取、词法回退、Go 闭包。"""
from sopcontrol.context import ProjectContext
from plugins.sensors.go_ast_scan import (
    GoAstScanSensor,
    go_import_candidates,
    go_import_closure,
    package_and_imports,
    static_references,
)

GATE = '''package gateway

import (
	"net/http"
	gw "example.com/internal/gateway"
)

// AdmitRequest 只在注释里出现不算引用
func HandleWrite(payload map[string]any) map[string]any {
	msg := "AdmitRequest 也不是字符串里的引用"
	return gw.AdmitRequest(payload)
}
'''


def test_references_exclude_comments_and_strings():
    refs = static_references(GATE)
    assert "AdmitRequest" in refs  # 真调用（gw.AdmitRequest）算引用
    assert "HandleWrite" in refs and "payload" in refs
    assert refs.count("AdmitRequest") == 1  # 注释与字符串里的不算，只此一处


def test_package_and_imports():
    package, imports = package_and_imports(GATE)
    assert package == "gateway"
    assert imports == ["example.com/internal/gateway", "net/http"]


def test_unparseable_source_signals_none():
    package, imports = package_and_imports("package {{{ broken")
    assert package is None and imports == []
    assert static_references("func broken(") == []


def test_sensor_falls_back_to_lexical_on_unparseable(tmp_path):
    """解析失败回退词法：kind 保留 go_scan.references，grounding 依 kind 如实标 lexical。"""
    (tmp_path / "broken.go").write_text("package {{{ broken", encoding="utf-8")
    ctx = ProjectContext(tmp_path)
    rows = GoAstScanSensor().observe(ctx)
    assert [r.kind for r in rows] == ["go_scan.references"]
    assert rows[0].observer == "go_ast_scan"


def test_sensor_emits_file_info_even_without_imports(tmp_path):
    """零 import 的生产文件也必须有 file_info：同包互见是 Go 可达性的主通路。

    这个回归位来自真实排障——file_info 只在有 import 时产出时，无 import 的
    生产文件进不了包索引，所有同包测试被误判 test_cannot_reach_consumer。
    """
    (tmp_path / "leaf.go").write_text("package gateway\n\nfunc Leaf() int { return 1 }\n", encoding="utf-8")
    rows = GoAstScanSensor().observe(ProjectContext(tmp_path))
    kinds = sorted(r.kind for r in rows)
    assert kinds == ["go_ast.file_info", "go_ast.references"]


def test_go_import_closure_same_package_and_imports():
    """闭包 = 同包互见 + import 末段匹配包声明名（近似规则见传感器 docstring）。"""
    packages = {
        "src/gate.go": "gateway",
        "src/api/client.go": "api",
        "src/api/client_test.go": "api",
        "pkg/util/log.go": "log",
    }
    adjacency = {
        # import 路径末段 == 对方包声明名（util 目录声明 package log 是合法 Go）
        "src/api/client.go": ["example.com/proj/pkg/log", "example.com/proj/gateway"],
    }
    closed = go_import_closure("src/api/client_test.go", packages, adjacency)
    # 同包互见：api 全体；import 传递：log 与 gateway 两个包
    assert "src/api/client.go" in closed
    assert "pkg/util/log.go" in closed
    assert "src/gate.go" in closed


def test_go_import_candidates_last_segment():
    assert go_import_candidates("example.com/proj/gateway") == {"gateway"}
    assert go_import_candidates("") == set()

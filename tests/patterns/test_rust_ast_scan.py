"""rust_ast_scan 单元测试：AST 引用、use/mod 模块边、词法回退边界（Go/TS 模板复制）。"""
from sopcontrol.context import ProjectContext
from plugins.sensors.rust_ast_scan import (
    RustAstScanSensor,
    module_edges,
    static_references,
)

GATE = '''
use crate::limiter::enforce_rate_limit;
use std::collections::HashMap;

// admit_request 只在注释里出现不算引用
pub fn handle_write(payload: &str) -> bool {
    let note = "admit_request 也不是字符串里的引用";
    admit_request(payload)
}
'''


def test_references_exclude_comments_and_strings():
    refs = static_references(GATE)  # 集合语义：同名只出现一次
    assert "admit_request" in refs and "handle_write" in refs
    # use 路径里的符号算本文件的引用（Python 侧 import 同口径：引入即消费）——
    # RS-003 的回归证据正来自 tests/limiter_test.rs 的 use 路径标识符
    assert "enforce_rate_limit" in refs and "limiter" in refs


def test_module_edges_use_paths_and_mods():
    src = '''
mod limiter;
use crate::gateway::admit_request;
use self::helper::thing;
use std::collections::HashMap;
'''
    edges = module_edges(_parse(src))
    assert "limiter" in edges        # mod 声明
    assert "gateway" in edges and "admit_request" in edges  # use 全段参与
    assert "helper" in edges and "thing" in edges
    assert "crate" not in edges and "self" not in edges    # 关键字段剔除
    assert "std" in edges and "collections" in edges       # 外部 crate 段是天然叶子


def _parse(source: str):
    from plugins.sensors.rust_ast_scan import _parse as parse
    return parse(source)


def test_unparseable_source_signals_none():
    assert static_references("pub fn broken( {") == []
    assert module_edges(_parse("use crate::{")) == []


def test_sensor_parseable_rs_never_falls_back_to_lexical(tmp_path):
    """解析成功的 .rs 不产词法证据（ts_ast 同源取舍：词法会给纯注释文件产假引用）。

    纯注释文件产且仅产一条空边 modules 行——这是设计而非遗漏：闭包索引靠它
    覆盖零 use 文件（替身现形机制），空边是天然叶子，无引用则永远进不了
    生产/测试两侧。
    """
    (tmp_path / "pure_comment.rs").write_text(
        "// admit_request 和 register_audit_hook 都只是注释\n", encoding="utf-8"
    )
    rows = RustAstScanSensor().observe(ProjectContext(tmp_path))
    assert [r.kind for r in rows] == ["rust_ast.modules"]
    assert rows[0].observed == []


def test_sensor_emits_modules_even_with_empty_edges(tmp_path):
    """零 use 的解析成功文件也必须产 modules 证据（空表）——Go file_info 教训的 Rust 版。

    tests/ 下的集成测试零 use 就真的到不了任何生产文件：没有这条空边证据，
    替身文件进不了闭包索引，reachability 会把它误当「没看见」而沉默。
    """
    (tmp_path / "double.rs").write_text(
        "fn admit_request(payload: &str) -> bool { !payload.is_empty() }\n",
        encoding="utf-8",
    )
    rows = RustAstScanSensor().observe(ProjectContext(tmp_path))
    kinds = sorted(r.kind for r in rows)
    assert kinds == ["rust_ast.modules", "rust_ast.references"]
    modules = next(r for r in rows if r.kind == "rust_ast.modules")
    assert modules.observed == []  # 零 use：空边，正是替身的形状


def test_sensor_unparseable_rs_falls_back_to_lexical(tmp_path):
    (tmp_path / "broken.rs").write_text("pub fn broken( {", encoding="utf-8")
    rows = RustAstScanSensor().observe(ProjectContext(tmp_path))
    assert [r.kind for r in rows] == ["rust_scan.references"]
    assert rows[0].observer == "rust_ast_scan"

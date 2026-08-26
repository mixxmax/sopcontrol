"""import_graph 薄卡。"""
from plugins.sensors.import_graph import (
    build_adjacency,
    import_closure,
    index_by_module,
    module_names,
    top_level_imports,
)
from sopcontrol.model import Evidence


def test_top_level_imports():
    src = "import os\nfrom pathlib import Path\nfrom . import x\n"
    mods = top_level_imports(src)
    assert "os" in mods and "pathlib" in mods


def test_build_adjacency():
    ev = [
        Evidence(
            kind="import_graph.imports",
            subject="src/a.py",
            observed=["os", "sys"],
            observer="import_graph",
            input_hash="h",
        )
    ]
    assert build_adjacency(ev) == {"src/a.py": ["os", "sys"]}


def test_module_names_covers_stem_and_package():
    # 传感器只记裸顶层名，所以包内文件既可能以 stem 也可能以包名被导入
    assert module_names("src/spec/validator.py") == {"validator", "src", "spec"}
    assert module_names("gateway.py") == {"gateway"}


def test_index_by_module_is_reverse_index():
    idx = index_by_module(["src/a.py", "src/b.py"])
    assert idx["a"] == ["src/a.py"]
    assert idx["src"] == ["src/a.py", "src/b.py"]


def test_import_closure_is_transitive():
    adjacency = {
        "tests/test_x.py": ["gateway"],
        "src/gateway.py": ["helper", "os"],
        "src/helper.py": [],
    }
    by_module = index_by_module(list(adjacency))
    modules, files = import_closure("tests/test_x.py", adjacency, by_module)
    assert "src/gateway.py" in files
    assert "src/helper.py" in files  # 二跳
    assert "os" in modules  # 索引不到文件的第三方名字自然成为叶子


def test_import_closure_stops_at_unlinked_files():
    adjacency = {"tests/test_x.py": ["other"], "src/gateway.py": []}
    by_module = index_by_module(list(adjacency))
    _, files = import_closure("tests/test_x.py", adjacency, by_module)
    assert files == {"tests/test_x.py"}

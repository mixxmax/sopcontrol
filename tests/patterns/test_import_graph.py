"""import_graph 薄卡。"""
from plugins.sensors.import_graph import build_adjacency, top_level_imports
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

"""import_graph：Python 文件级 import 邻接（E3 薄卡）。

不做全调用图；只记录「本文件 import 了哪些顶层模块名」，供项目认知与日后加深。
"""
from __future__ import annotations

import ast

from sopcontrol.context import ProjectContext, file_hash, is_production_path
from sopcontrol.model import Evidence


def top_level_imports(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    return sorted(m for m in mods if len(m) >= 2)


class ImportGraphSensor:
    sensor_id = "import_graph"

    def observe(self, ctx: ProjectContext) -> list[Evidence]:
        out: list[Evidence] = []
        for path in ctx.iter_files({".py"}):
            rel = ctx.rel(path)
            if not is_production_path(rel) and not rel.startswith("tests/"):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            imports = top_level_imports(text)
            if not imports:
                continue
            out.append(
                Evidence(
                    kind="import_graph.imports",
                    subject=rel,
                    observed=imports,
                    observer=self.sensor_id,
                    input_hash=file_hash(path),
                )
            )
        return out


def build_adjacency(evidence: list[Evidence]) -> dict[str, list[str]]:
    """subject → imported modules（仅 import_graph.imports）。"""
    adj: dict[str, list[str]] = {}
    for ev in evidence:
        if ev.kind != "import_graph.imports":
            continue
        adj[ev.subject] = list(ev.observed or [])
    return dict(sorted(adj.items()))

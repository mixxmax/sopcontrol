"""ast_scan 传感器：Python 文件的 AST 级引用索引（E3）。

注释、文档字符串、普通字符串里的词不算引用——根治首夜"注释假消费者"教训
（RESIDUAL_RISKS R1 反向家族）。不可解析文件留给 grep 层兜底。
"""
from __future__ import annotations

import ast

from sopcontrol.context import ProjectContext, file_hash
from sopcontrol.model import Evidence


def static_references(source: str) -> list[str]:
    """AST 中真实出现的符号：Name、属性、定义名、导入绑定。"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Global):
            names.update(node.names)
    return sorted(n for n in names if len(n) >= 3)  # 与 grep 阈值一致


class AstScanSensor:
    sensor_id = "ast_scan"

    def observe(self, ctx: ProjectContext) -> list[Evidence]:
        out: list[Evidence] = []
        for path in ctx.iter_files({".py"}):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            refs = static_references(text)
            if not refs:
                continue  # 空/不可解析：交给 code_scan 兜底
            out.append(
                Evidence(
                    kind="ast_scan.references",
                    subject=ctx.rel(path),
                    observed=refs,
                    observer=self.sensor_id,
                    input_hash=file_hash(path),
                )
            )
        return out

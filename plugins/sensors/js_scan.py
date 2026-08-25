"""js_scan 传感器：JS/TS 的引用索引（E3）。

移植 ast_scan 的核心思路——注释与字符串里的词不算引用——但不引入 TS 解析器
依赖（脊柱只许 pydantic/PyYAML/pytest）。用确定性词法剥离后抽标识符。
"""
from __future__ import annotations

import re

from sopcontrol.context import ProjectContext, file_hash
from sopcontrol.model import Evidence

JS_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]{2,}")


def strip_comments_and_strings(source: str) -> str:
    """剥离 //、/* */、引号/模板字符串；保留换行以维持行结构。不可嵌套模板。"""
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""

        if ch == "/" and nxt == "/":
            i += 2
            while i < n and source[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (source[i] == "*" and source[i + 1] == "/"):
                if source[i] == "\n":
                    out.append("\n")
                i += 1
            i = min(i + 2, n)
            continue
        if ch in {'"', "'", "`"}:
            quote = ch
            i += 1
            while i < n:
                if source[i] == "\\":
                    i += 2
                    continue
                if source[i] == quote:
                    i += 1
                    break
                if source[i] == "\n":
                    out.append("\n")
                i += 1
            continue

        out.append(ch)
        i += 1
    return "".join(out)


def static_references(source: str) -> list[str]:
    code = strip_comments_and_strings(source)
    return sorted({m for m in IDENT_RE.findall(code) if len(m) >= 3})


class JsScanSensor:
    sensor_id = "js_scan"

    def observe(self, ctx: ProjectContext) -> list[Evidence]:
        out: list[Evidence] = []
        for path in ctx.iter_files(JS_SUFFIXES):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            refs = static_references(text)
            if not refs:
                continue
            out.append(
                Evidence(
                    kind="js_scan.references",
                    subject=ctx.rel(path),
                    observed=refs,
                    observer=self.sensor_id,
                    input_hash=file_hash(path),
                )
            )
        return out

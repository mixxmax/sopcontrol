"""rust_scan：Rust 文件引用索引（E3）。移植 go/js 词法剥离思路——注释/字符串不算引用。"""
from __future__ import annotations

import re

from sopcontrol.context import ProjectContext, file_hash
from sopcontrol.model import Evidence

RUST_SUFFIXES = {".rs"}
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def strip_comments_and_strings(source: str) -> str:
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
        if ch == '"':
            i += 1
            while i < n:
                if source[i] == "\\":
                    i += 2
                    continue
                if source[i] == '"':
                    i += 1
                    break
                if source[i] == "\n":
                    out.append("\n")
                i += 1
            continue
        if ch == "'":
            # 字符字面量：简单跳过到下一单引号
            i += 1
            while i < n and source[i] != "'":
                if source[i] == "\\":
                    i += 2
                    continue
                i += 1
            i = min(i + 1, n)
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def static_references(source: str) -> list[str]:
    return sorted({m for m in IDENT_RE.findall(strip_comments_and_strings(source)) if len(m) >= 3})


class RustScanSensor:
    sensor_id = "rust_scan"

    def observe(self, ctx: ProjectContext) -> list[Evidence]:
        out: list[Evidence] = []
        for path in ctx.iter_files(RUST_SUFFIXES):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            refs = static_references(text)
            if not refs:
                continue
            out.append(
                Evidence(
                    kind="rust_scan.references",
                    subject=ctx.rel(path),
                    observed=refs,
                    observer=self.sensor_id,
                    input_hash=file_hash(path),
                )
            )
        return out

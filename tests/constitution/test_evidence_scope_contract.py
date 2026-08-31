"""传感器路径证据与规则 scope 白名单必须保持精确同步。"""
from __future__ import annotations

import ast
from pathlib import Path

from sopcontrol.scope import PATH_SCOPED_EVIDENCE_KINDS
from sopcontrol.trace import TRACE_KIND

ROOT = Path(__file__).resolve().parents[2]
SENSOR_DIR = ROOT / "plugins" / "sensors"
PATH_SUBJECT_FORMS = {"ctx.rel(path)", "rel"}


def _direct_sensor_evidence_kinds() -> frozenset[str]:
    kinds: set[str] = set()
    for source_path in sorted(SENSOR_DIR.glob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Evidence"
            ):
                continue
            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            kind = keywords.get("kind")
            subject = keywords.get("subject")
            assert isinstance(kind, ast.Constant) and isinstance(kind.value, str), (
                f"{source_path}: Evidence kind 必须是可审计的字符串字面量"
            )
            assert subject is not None
            assert ast.unparse(subject) in PATH_SUBJECT_FORMS, (
                f"{source_path}: 路径 Evidence subject 来源未经 scope 契约审查"
            )
            kinds.add(kind.value)
    return frozenset(kinds)


def test_sensor_path_evidence_kinds_match_scope_contract():
    assert _direct_sensor_evidence_kinds() == PATH_SCOPED_EVIDENCE_KINDS


def test_trace_evidence_remains_project_scoped():
    assert TRACE_KIND == "harness.trace"
    assert TRACE_KIND not in PATH_SCOPED_EVIDENCE_KINDS

"""变异器：把 corpus/mutations.yaml 里声明的每次「退回修复」实现成可执行的替换。

为什么必须是代码而不是数据：退回一个修复要替换模块属性（常量、函数），
YAML 描述不了。所以 mutations.yaml 负责声明意图与必须报警的对照，本模块负责
实现退回动作，两边由 mutation_id 对齐（test_mutations.py 守卫两边一一对应）。

`from X import Y` 的陷阱：no_consumer.py 写的是 `from sopcontrol.context import
is_test_path`，导入时就把函数对象绑进了自己的命名空间。只 patch 定义模块对导入方
毫无影响——每个导入方都是一个独立的 patch 目标。故凡是被 import 进别处的名字，
一律走 _patch_everywhere；只改常量的（is_test_path 内部按调用时读取）不受影响。
"""
from __future__ import annotations

import sopcontrol.context as context
import sopcontrol.verdict as verdict
from plugins.detectors import no_consumer, reachability, state_health
from plugins.sensors import import_graph

# 会把 context / verdict / import_graph 的名字 import 进自己命名空间的模块（grep 得来，
# 新增导入方若漏登记，_patch_everywhere 的自检会在变异不生效时暴露出来）
_IMPORTERS = [context, verdict, no_consumer, state_health, import_graph, reachability]


def _patch_everywhere(mp, attr: str, value) -> None:
    """在定义模块与所有导入方命名空间里同时替换，命中数为 0 视为登记失效。"""
    hits = 0
    for mod in _IMPORTERS:
        if hasattr(mod, attr):
            mp.setattr(mod, attr, value, raising=True)
            hits += 1
    assert hits, f"没有任何模块暴露 {attr}——变异器登记已过期"


def mut_001_forget_colocated_tests(mp) -> None:
    """清空同置测试命名（foo_test.go / foo.test.ts）→ 回归文件被读成生产文件。"""
    mp.setattr(context, "_COLOCATED_TEST_SUFFIXES", ())


def mut_002_spec_dir_is_test(mp) -> None:
    """把 spec 放回测试目录名 → 任意深度的 src/spec/ 都被当成测试。"""
    mp.setattr(context, "_TEST_DIR_HINTS", context._TEST_DIR_HINTS | {"spec"})


def mut_003_no_repo_wide_refs(mp) -> None:
    """referenced_anywhere 返回空集 → 只要本文件没有结构化引用就算「只在注释里」。"""
    _patch_everywhere(mp, "referenced_anywhere", lambda structured: set())


def mut_004_no_state_rule_exemption(mp) -> None:
    """取消状态类规则的豁免 → 它们额外挨一条 consumer_markers_undefined。"""
    _patch_everywhere(mp, "state_rule_handled_elsewhere", lambda rule: False)


def mut_005_legacy_ignores_path(mp) -> None:
    """去掉生产路径过滤 → 测试里断言「旧符号已消失」也算旧链存活。"""

    def legacy_evidence(rule, evidence):
        if not rule.legacy_markers:
            return []
        return [e for e in evidence if verdict.marker_hit(e, rule.legacy_markers)]

    _patch_everywhere(mp, "legacy_evidence", legacy_evidence)


def mut_006_blind_write_sites(mp) -> None:
    """_write_sites 恒返回 None → 退回「出现在几个文件」，读取方被算成维护方。"""
    _patch_everywhere(mp, "_write_sites", lambda rule, evidence: None)


def mut_007_reads_must_be_local(mp) -> None:
    """只在写入该字段的文件内部找读取 → 跨文件的读写闭合被判成无人读取。"""

    def _unread_schema_fields(rule, evidence):
        writes: dict[str, set[str]] = {}
        reads_by_file: dict[str, set[str]] = {}
        for ev in evidence:
            if ev.kind != "ast_scan.name_flows":
                continue
            obs = ev.observed or {}
            if not isinstance(obs, dict) or not context.is_production_path(ev.subject):
                continue
            for w in obs.get("writes") or []:
                writes.setdefault(str(w), set()).add(ev.subject)
            reads_by_file.setdefault(ev.subject, set()).update(
                str(r) for r in obs.get("reads") or []
            )
        unread = [
            m for m in rule.state_markers
            if m in writes
            and not any(m in reads_by_file.get(f, set()) for f in writes[m])
        ]
        files: set[str] = set()
        for m in unread:
            files |= writes.get(m, set())
        return unread, sorted(files)

    _patch_everywhere(mp, "_unread_schema_fields", _unread_schema_fields)


def mut_008_no_test_dirs(mp) -> None:
    """is_test_path 恒假 → 全部回归证据消失，正向对照退化成「接了线但没测」。"""
    _patch_everywhere(mp, "is_test_path", lambda relpath: False)


def mut_009_stem_only_module_names(mp) -> None:
    """module_names 只认 stem → 包内文件（src/spec/validator.py）按包名对不上，判成不可达。

    退回的是「stem ∪ 父目录名」这个对齐方式。传感器记的 import 只有裸顶层名，
    包内生产文件要靠父目录名才认得出来；只认 stem 时闭包走不到它，正确接线的
    回归测试会被误报 test_cannot_reach_consumer——过度告警方向的失效。
    """
    from pathlib import PurePosixPath

    _patch_everywhere(
        mp, "module_names", lambda relpath: {PurePosixPath(relpath).stem}
    )


def mut_010_go_closure_blind(mp) -> None:
    """go_import_closure 恒返回空集 → 同包/同 import 的 Go 回归全部判成不可达。

    Go 分支的过度告警守卫（对称于 MUT-009 之于 Python）：包/import 证据瞎了，
    go-gateway 的正向对照会全部误报 test_cannot_reach_consumer——用户一旦发现
    「接对了也报警」，就会绕开控制器而不是修复它。
    """
    _patch_everywhere(
        mp, "go_import_closure", lambda start, packages, adjacency: set()
    )


MUTATORS = {
    "MUT-001": mut_001_forget_colocated_tests,
    "MUT-002": mut_002_spec_dir_is_test,
    "MUT-003": mut_003_no_repo_wide_refs,
    "MUT-004": mut_004_no_state_rule_exemption,
    "MUT-005": mut_005_legacy_ignores_path,
    "MUT-006": mut_006_blind_write_sites,
    "MUT-007": mut_007_reads_must_be_local,
    "MUT-008": mut_008_no_test_dirs,
    "MUT-009": mut_009_stem_only_module_names,
    "MUT-010": mut_010_go_closure_blind,
}

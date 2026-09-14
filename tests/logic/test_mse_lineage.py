"""§26 lineage 组：谓词证明防伪造、基数不变量、快照失效、存储原子性。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from sopcontrol.lineage import LineageStore, SetLineage, verify_lineage

from conftest import make_lineage


def _operators():
    from sopcontrol.operator_contract import OperatorContract

    ops = {}
    for oid, role, preds, card in (
            ("jobs.search", "source", [], "unknown"),
            ("jobs.filter_date", "reducer", ["published_within"], "reduce"),
            ("jobs.exclude_existing", "anti_join", ["not_in_table"], "reduce"),
            ("jobs.score", "scorer", [], "preserve"),
            ("jobs.enrich_all", "enricher", [], "preserve"),
    ):
        ops[oid] = OperatorContract(operator_id=oid, role=role,
                                    produces={"predicates": preds},
                                    cardinality={"effect": card})
    return ops


def test_score_input_requires_target_predicates():
    """scorer 不能自报 not_in_table：证明只能来自声明能产生该谓词的 operator。"""
    ops = _operators()
    lin = make_lineage("s1", "jobs.score", 5,
                       predicates=["not_in_table"])
    problems = verify_lineage(lin, operators=ops, known={})
    assert any("未声明能产生谓词" in p for p in problems)


def test_reducer_cannot_expand_cardinality():
    ops = _operators()
    s0 = make_lineage("s0", "jobs.search", 100)
    lin = make_lineage("s1", "jobs.filter_date", 150, parents=["s0"],
                       predicates=["published_within"])
    problems = verify_lineage(lin, operators=ops, known={"s0": s0})
    assert any("reducer 输出 cardinality" in p for p in problems)


def test_anti_join_cannot_expand_left_input():
    ops = _operators()
    s0 = make_lineage("s0", "jobs.search", 50)
    lin = make_lineage("s1", "jobs.exclude_existing", 80, parents=["s0"],
                       predicates=["not_in_table"])
    problems = verify_lineage(lin, operators=ops, known={"s0": s0})
    assert any("anti_join" in p for p in problems)


def test_enricher_preserves_cardinality_by_default():
    ops = _operators()
    s0 = make_lineage("s0", "jobs.search", 50)
    lin = make_lineage("s1", "jobs.enrich_all", 51, parents=["s0"])
    problems = verify_lineage(lin, operators=ops, known={"s0": s0})
    assert any("enricher" in p for p in problems)


def test_stale_membership_snapshot_invalidates_not_in_table():
    ops = _operators()
    lin = make_lineage("s1", "jobs.exclude_existing", 5,
                       predicates=["not_in_table"], snapshot="snap-old")
    lin.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    problems = verify_lineage(lin, operators=ops, known={},
                              now=datetime.now(timezone.utc))
    assert any("过期" in p for p in problems)


def test_parent_set_missing_is_reported():
    ops = _operators()
    lin = make_lineage("s9", "jobs.filter_date", 10, parents=["ghost"],
                       predicates=["published_within"])
    problems = verify_lineage(lin, operators=ops, known={})
    assert any("parent set 不存在" in p for p in problems)


def test_store_roundtrip_and_atomic_write(tmp_path):
    store = LineageStore(tmp_path)
    lin = make_lineage("s1", "jobs.filter_date", 7,
                       predicates=["published_within"])
    store.save(lin)
    loaded = store.load("s1")
    assert loaded is not None and loaded.cardinality == 7
    assert loaded.predicate_ids() == ["published_within"]
    # 无残留临时文件
    leftovers = [p for p in store.dir.iterdir() if p.name.startswith(".lineage.")]
    assert leftovers == []
    assert store.load("missing") is None
    assert store.delete("s1") is True and store.load("s1") is None


def test_corrupt_lineage_file_fails_open_as_missing(tmp_path):
    store = LineageStore(tmp_path)
    store.dir.mkdir(parents=True)
    (store.dir / "bad.json").write_text("{broken", encoding="utf-8")
    assert store.load("bad") is None
    assert store.load_all().get("bad") is None


def test_lineage_contains_no_business_content():
    """§24.1：沿袭只存摘要——模型字段里没有任何正文容器。"""
    lin = make_lineage("s1", "jobs.filter_date", 3)
    data = lin.model_dump()
    allowed = {"schema_version", "set_id", "entity_type", "producer_operator_id",
               "producer_step_id", "parent_set_ids", "predicates_proven",
               "fields_available", "cardinality", "content_digest",
               "source_snapshot_digest", "operator_digest", "goal_digest",
               "plan_digest", "created_at", "expires_at"}
    assert set(data) <= allowed
    # PredicateProof 也只含摘要字段
    proof = {"predicate_id", "parameters_digest", "producer_operator_id",
             "evidence_digest", "source_snapshot_digest"}
    for p in data["predicates_proven"]:
        assert set(p) <= proof


def test_model_text_cannot_forge_predicate_proof():
    """§24.2：产品只提供自由文本"已过滤"时判 unproven——没有 evidence 的
    证明在 verify 时暴露（producer 一致但谓词不在契约中）。"""
    ops = _operators()
    lin = make_lineage("s1", "jobs.filter_date", 3,
                       predicates=["title_matches"])  # filter_date 不产生该谓词
    problems = verify_lineage(lin, operators=ops, known={})
    assert problems  # 伪造被识破

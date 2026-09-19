"""C4：确认/编译同一锁事务 + 候选存储并发一致性（证据语义）。"""
from __future__ import annotations

import pytest

from sopcontrol.cli import main
from sopcontrol.learning import read_learning_confirmation_secret
from sopcontrol.model import RuleStatus
from sopcontrol.registry import Registry


@pytest.fixture()
def project(tmp_path):
    assert main(["init", str(tmp_path)]) == 0
    return tmp_path


def _confirm_permanent(project, candidate_id: str, decision: str = "keep_longterm", **kwargs):
    from sopcontrol.dynamic_sop import confirm_candidate

    first = confirm_candidate(project, candidate_id, decision, **kwargs)
    assert first.get("status") == "needs_user", first
    conf_id = first["confirmation_id"]
    secret = read_learning_confirmation_secret(project, conf_id)
    return confirm_candidate(
        project, candidate_id, decision,
        confirmation_id=conf_id, confirmation_secret=secret, **kwargs,
    )


def test_concurrent_confirms_keep_registry_coherent(project):
    """C4：并发确认同一锁事务——多线程确认不同候选，registry 无丢失、无重复、无坏证据。"""
    import threading

    from sopcontrol.dynamic_sop import compile_rule, observe_utterance

    barrier = threading.Barrier(4)
    errors: list = []
    rids: list = []

    def worker(i: int):
        try:
            _o, cand, _ = observe_utterance(
                project, quote=f"并发审计规则第{i}条必须先台账后评分",
                source_ref=f"sess-{i}")
            result = _confirm_permanent(project, cand.candidate_id)
            barrier.wait(timeout=60)
            receipt = compile_rule(project, result["rule_id"])
            rids.append(result["rule_id"])
            assert receipt["compile_digest"]
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=120)
    assert not errors, errors
    rules = Registry(project / ".sopcontrol" / "rules" / "registry.yaml").load()
    got = {r.rule_id for r in rules if r.rule_id in rids}
    assert got == set(rids) and len(rids) == 4
    for r in rules:
        if r.rule_id in got:
            assert r.status == RuleStatus.compiled
            assert r.compile_digest and r.compiled_at is not None

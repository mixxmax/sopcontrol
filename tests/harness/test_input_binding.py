"""最终闭环输入绑定矩阵（§15.3/§9.4）：初始配置/入口/预期/为何不能复用旧摘要。"""
from __future__ import annotations

import os

import pytest

from sopcontrol.control_result import idempotency_key
from sopcontrol.task import submit_input_digest_for


def _digest(work, *paths):
    return submit_input_digest_for(work, list(paths))


def test_single_file_same_size_content_change(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"0" * 100 + b"A")
    d1 = _digest(tmp_path, "a.txt")
    f.write_bytes(b"0" * 100 + b"B")
    assert _digest(tmp_path, "a.txt") != d1


def test_directory_content_change_add_delete_rename(tmp_path):
    d = tmp_path / "mat"
    d.mkdir()
    (d / "one.txt").write_text("1", encoding="utf-8")
    base = _digest(tmp_path, "mat")
    (d / "one.txt").write_text("2", encoding="utf-8")
    assert _digest(tmp_path, "mat") != base
    (d / "two.txt").write_text("2", encoding="utf-8")
    assert _digest(tmp_path, "mat") != base
    (d / "two.txt").unlink()
    (d / "one.txt").rename(d / "uno.txt")
    assert _digest(tmp_path, "mat") != base


def test_directory_order_stable_and_empty_vs_missing(tmp_path):
    import shutil as _shutil

    d = tmp_path / "w"
    d.mkdir()
    (d / "b").write_text("b", encoding="utf-8")
    (d / "a").write_text("a", encoding="utf-8")
    first = _digest(tmp_path, "w")
    _shutil.rmtree(d)
    d.mkdir()
    (d / "a").write_text("a", encoding="utf-8")
    (d / "b").write_text("b", encoding="utf-8")
    assert _digest(tmp_path, "w") == first  # 创建顺序不影响摘要
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _digest(tmp_path, "empty") != _digest(tmp_path, "no-such-dir")


def test_escape_symlink_loop_and_special_rejected_or_marked(tmp_path):
    with pytest.raises(ValueError):
        _digest(tmp_path, "../escaped")
    link = tmp_path / "loop"
    try:
        link.symlink_to(link)
    except OSError:
        pytest.skip("平台不支持 symlink")
    d1 = _digest(tmp_path, "loop")
    assert "symlink" in d1 or "loop" in d1 or d1.startswith("in-")
    target = tmp_path / "real.txt"
    target.write_text("v", encoding="utf-8")
    (tmp_path / "alias").symlink_to(target)
    assert _digest(tmp_path, "alias") == _digest(tmp_path, "real.txt")
    fifo = tmp_path / "pipe"
    try:
        os.mkfifo(fifo)
    except (OSError, AttributeError):
        pytest.skip("平台不支持 fifo")
    marked = _digest(tmp_path, "pipe")
    assert marked.startswith("in-")


def test_large_file_streaming_hash(tmp_path):
    big = tmp_path / "big.bin"
    with open(big, "wb") as fh:
        for _ in range(40):
            fh.write(b"Z" * (256 * 1024))
    d1 = _digest(tmp_path, "big.bin")
    with open(big, "r+b") as fh:
        fh.seek(5 * 1024 * 1024)
        fh.write(b"Q")
    assert _digest(tmp_path, "big.bin") != d1


def _key(**kw):
    from sopcontrol.control_result import ControlResult

    base = {"result_id": "k", "task_id": "T", "profile_id": "p",
            "profile_revision": 1, "effective_plan_digest": "plan-1",
            "input_digest": "in-1", "baseline_digest": "base-1",
            "checked_dimensions": ["check-a"], "check_id": "check-a"}
    base.update(kw)
    return idempotency_key(ControlResult.model_validate(base))


def test_idempotency_key_binds_all_dimensions():
    k0 = _key()
    assert _key() == k0  # 同输入稳定
    assert _key(input_digest="in-2") != k0  # 输入变
    assert _key(baseline_digest="base-2") != k0  # 基线变
    assert _key(effective_plan_digest="plan-2") != k0  # 计划变
    assert _key(check_id="check-b",
                checked_dimensions=["check-b"]) != k0  # check_id 变
    from sopcontrol.control_result import IDEM_SCHEMA_VERSION

    assert IDEM_SCHEMA_VERSION == "1"

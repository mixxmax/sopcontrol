"""输入变化使旧证据 stale（手册 14.1 场景14 / DESIGN §4）。

账本追加不删旧行；消费者（explain/doctor）必须按当前文件 hash 过滤，
不得拿过期 input_hash 的证据做通过判定。
"""
from __future__ import annotations

from pathlib import Path

from .context import file_hash
from .model import Evidence
from .testrun import TEST_RUN_KIND, source_digest


def is_input_stale(root: Path, ev: Evidence) -> bool:
    """subject 对应文件不存在或内容 hash ≠ input_hash → stale。

    E4 测试运行证据例外：它的 input_hash 是被测源码集合的指纹，不是 subject
    单文件的 hash，所以按源码集合重算。源码改一个字节，上一轮的绿就不再算数。
    """
    path = Path(root) / ev.subject
    if not path.is_file():
        return True
    if ev.kind == TEST_RUN_KIND:
        try:
            return source_digest(root) != ev.input_hash
        except OSError:
            return True
    try:
        return file_hash(path) != ev.input_hash
    except OSError:
        return True


def partition_evidence(
    root: Path, evidence: list[Evidence]
) -> tuple[list[Evidence], list[Evidence]]:
    """返回 (fresh, stale)。过期 valid_until 的也算 stale 侧。"""
    fresh, stale = [], []
    for ev in evidence:
        if ev.is_expired() or is_input_stale(root, ev):
            stale.append(ev)
        else:
            fresh.append(ev)
    return fresh, stale

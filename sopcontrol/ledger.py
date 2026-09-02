"""追加式账本：Evidence 与 Finding 的 append-only JSONL 存储。

内容寻址去重：同一现场重复审计产生相同记录 id，追加时跳过，账本幂等。
日常路径只追加；役用清理用 replace_snapshot 整轮替换（非逐条篡改）。

并发：同一路径进程内 RLock + 跨进程 flock；append 与 compact 共享锁域。
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Iterator

from .model import Evidence, Finding, content_hash


class _LedgerPathLock:
    def __init__(self) -> None:
        self.thread_lock = threading.RLock()
        self.local = threading.local()


_PATH_LOCKS: dict[str, _LedgerPathLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _lock_path(self) -> Path:
        resolved = self.path.resolve()
        # Prefer project-local lock dir when under .sopcontrol/evidence/
        if (
            resolved.parent.name == "evidence"
            and resolved.parent.parent.name == ".sopcontrol"
        ):
            root = resolved.parent.parent.parent
        else:
            root = resolved.parent
        return root / ".sopcontrol-local" / "locks" / f"ledger-{content_hash(str(resolved))}.lock"

    @contextmanager
    def exclusive(self):
        """同一账本路径的进程内与跨进程可重入写锁。"""
        key = str(self.path.resolve())
        with _PATH_LOCKS_GUARD:
            state = _PATH_LOCKS.setdefault(key, _LedgerPathLock())
        with state.thread_lock:
            depth = getattr(state.local, "depth", 0)
            if depth == 0:
                lock_path = self._lock_path()
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                descriptor = lock_path.open("a+")
                fcntl.flock(descriptor.fileno(), fcntl.LOCK_EX)
                state.local.descriptor = descriptor
            state.local.depth = depth + 1
            try:
                yield
            finally:
                state.local.depth -= 1
                if state.local.depth == 0:
                    descriptor = state.local.descriptor
                    fcntl.flock(descriptor.fileno(), fcntl.LOCK_UN)
                    descriptor.close()
                    del state.local.descriptor

    def _existing_ids(self) -> set[str]:
        ids: set[str] = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    ids.add(rec.get("evidence_id") or rec.get("finding_id"))
                except json.JSONDecodeError:
                    continue
        return {item for item in ids if item}

    def _append(self, record: Evidence | Finding, id_field: str) -> str:
        rid = getattr(record, id_field)
        with self.exclusive():
            if rid not in self._existing_ids():
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(record.model_dump_json() + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
        return rid

    def append_evidence(self, evidence: Evidence) -> str:
        return self._append(evidence, "evidence_id")

    def append_finding(self, finding: Finding) -> str:
        return self._append(finding, "finding_id")

    def replace_snapshot(self, evidence: list[Evidence], findings: list[Finding]) -> None:
        """用本轮审计结果整体替换账本，去掉因文件变更累积的 stale 噪音。"""
        lines = [e.model_dump_json() for e in evidence]
        lines.extend(f.model_dump_json() for f in findings)
        payload = ("\n".join(lines) + "\n") if lines else ""
        with self.exclusive():
            parent = self.path.parent
            parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=str(parent),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(payload)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_name, self.path)
                dir_fd = os.open(str(parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise

    def _records(self) -> Iterator[dict]:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                yield json.loads(line)

    def load_evidence(self, current_only: bool = True) -> list[Evidence]:
        out = []
        for rec in self._records():
            if "evidence_id" not in rec:
                continue
            ev = Evidence.model_validate(rec)
            if current_only and ev.is_expired():
                continue
            out.append(ev)
        return out

    def load_findings(self) -> list[Finding]:
        return [
            Finding.model_validate(rec)
            for rec in self._records()
            if "finding_id" in rec
        ]

    def verify(self) -> bool:
        """内容寻址校验：任何一行的 id 与内容不符（被篡改/损坏）即返回 False。"""
        try:
            for rec in self._records():
                if "evidence_id" in rec:
                    if Evidence.model_validate(rec).compute_id() != rec["evidence_id"]:
                        return False
                elif "finding_id" in rec:
                    if Finding.model_validate(rec).compute_id() != rec["finding_id"]:
                        return False
                else:
                    return False
        except Exception:
            return False
        return True

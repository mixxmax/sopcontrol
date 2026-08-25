"""追加式账本：Evidence 与 Finding 的 append-only JSONL 存储。

内容寻址去重：同一现场重复审计产生相同记录 id，追加时跳过，账本幂等。
日常路径只追加；役用清理用 replace_snapshot 整轮替换（非逐条篡改）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from .model import Evidence, Finding


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _existing_ids(self) -> set[str]:
        ids: set[str] = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ids.add(json.loads(line).get("evidence_id") or json.loads(line).get("finding_id"))
                except json.JSONDecodeError:
                    continue
        return ids

    def _append(self, record: Evidence | Finding, id_field: str) -> str:
        rid = getattr(record, id_field)
        if rid not in self._existing_ids():
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(record.model_dump_json() + "\n")
        return rid

    def append_evidence(self, evidence: Evidence) -> str:
        return self._append(evidence, "evidence_id")

    def append_finding(self, finding: Finding) -> str:
        return self._append(finding, "finding_id")

    def replace_snapshot(self, evidence: list[Evidence], findings: list[Finding]) -> None:
        """用本轮审计结果整体替换账本，去掉因文件变更累积的 stale 噪音。"""
        lines = [e.model_dump_json() for e in evidence]
        lines.extend(f.model_dump_json() for f in findings)
        self.path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")

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

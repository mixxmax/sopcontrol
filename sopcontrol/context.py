"""目标项目的只读视图：受控的文件遍历与测试路径启发式。"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

EXCLUDED_DIRS = {
    ".git", ".sopcontrol", ".sopcontrol-local", "node_modules",
    "__pycache__", ".venv", ".pytest_cache", "dist", "build",
}

_TEST_DIR_HINTS = {"tests", "test", "spec", "__tests__"}


def is_test_path(relpath: str) -> bool:
    parts = PurePosixPath(relpath).parts
    if any(p.lower() in _TEST_DIR_HINTS for p in parts[:-1]):
        return True
    name = parts[-1].lower()
    return name.startswith("test_") or name.endswith("_test.py") or "conftest" in name


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


@dataclass
class ProjectContext:
    root: Path

    def iter_files(self, suffixes: set[str], limit: int = 500):
        root = str(self.root)
        count = 0
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
            for name in sorted(filenames):
                if Path(name).suffix in suffixes:
                    count += 1
                    if count > limit:
                        return
                    yield Path(dirpath) / name

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

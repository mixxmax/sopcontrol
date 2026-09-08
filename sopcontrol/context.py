"""目标项目的只读视图：受控的文件遍历与测试路径启发式。"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

EXCLUDED_DIRS = {
    ".git", ".sopcontrol", ".sopcontrol-local", "node_modules",
    "__pycache__", ".venv", ".pytest_cache", "dist", "build",
    # 工作树/本地工具目录会先于主树占满 iter_files 上限，掩盖真生产消费者
    ".worktrees", ".dsh", ".pnpm-store", ".planning",
}

_TEST_DIR_HINTS = {"tests", "test", "__tests__"}
# 语料/文档不是生产消费者——模式名写在 patterns.yaml 不算接线（自应用役用教训）
_META_ROOTS = frozenset({"corpus", "docs"})

# 与测试文件同置的命名约定。Go 强制 `foo_test.go` 与 `foo.go` 同目录，JS/TS 生态
# 普遍把 `foo.test.ts` 放在被测文件旁边——只认 `tests/` 目录会把这些回归文件读成
# 生产消费者，于是「有测试」被判成「无回归证据」。R2 的一个方向。
_COLOCATED_TEST_SUFFIXES = (
    "_test.py", "_test.go", "_test.rs", "_test.ts", "_test.js",
    ".test.ts", ".test.tsx", ".test.js", ".test.jsx", ".test.mjs", ".test.cjs",
    ".spec.ts", ".spec.tsx", ".spec.js", ".spec.jsx", ".spec.mjs", ".spec.cjs",
)


class FileScanLimitExceeded(RuntimeError):
    """扫描预算不足以覆盖项目时显式失败，禁止把部分结果冒充完整证据。"""

    def __init__(self, *, limit: int, suffixes: set[str]) -> None:
        rendered = ", ".join(sorted(suffixes)) or "（无后缀）"
        super().__init__(
            f"文件扫描超过上限 {limit}（后缀: {rendered}）；"
            "证据覆盖不完整，不能继续判定"
        )


def is_test_path(relpath: str) -> bool:
    parts = PurePosixPath(relpath).parts
    if any(p.lower() in _TEST_DIR_HINTS for p in parts[:-1]):
        return True
    # 「spec」两义：根级 spec/ 是 RSpec/Jasmine 的测试根，嵌套 spec/ 基本都是
    # OpenAPI / JSON Schema 一类的生产代码（src/spec/loader.py）。一律当测试
    # 会把真的生产消费者判没，于是 test_helper_only 在正确代码上报警。
    if len(parts) > 1 and parts[0].lower() == "spec":
        return True
    name = parts[-1].lower()
    if name.startswith("test_") or "conftest" in name:
        return True
    return name.endswith(_COLOCATED_TEST_SUFFIXES)


def is_meta_path(relpath: str) -> bool:
    parts = PurePosixPath(relpath).parts
    return bool(parts) and parts[0] in _META_ROOTS


def is_production_path(relpath: str) -> bool:
    """吸收判定用的生产路径：非测试、非语料/文档。"""
    return not is_test_path(relpath) and not is_meta_path(relpath)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _load_scan_excludes(root: Path) -> tuple[tuple[str, ...], ...]:
    """manifest 的 scan_excludes：仓库相对目录前缀，按路径分量匹配。

    配置错误 fail-closed：排除声明不可信 = 覆盖完整性声明不可信，
    宁可拒绝出报告也不冒充完整证据。
    """
    manifest = root / ".sopcontrol" / "manifest.yaml"
    try:
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ()
    raw = data.get("scan_excludes") or []
    if not isinstance(raw, list):
        raise ValueError("manifest scan_excludes 必须是路径前缀列表")
    out = []
    for item in raw:
        prefix = str(item).strip()
        pure = PurePosixPath(prefix)
        parts = pure.parts
        if (
            not prefix
            or pure.is_absolute()
            or ".." in parts
            or any(part in {"", "."} for part in parts)
        ):
            raise ValueError(
                f"manifest scan_excludes 非法条目 {item!r}：只接受仓库内相对目录前缀"
            )
        out.append(parts)
    return tuple(out)


@dataclass
class ProjectContext:
    root: Path
    scan_excludes: tuple[tuple[str, ...], ...] = field(
        default_factory=tuple, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.scan_excludes = _load_scan_excludes(self.root)

    @staticmethod
    def _is_tool_state(name: str) -> bool:
        # git 生态惯例：点目录是工具状态（.git/.venv/.codex-worktrees/.agents/…），
        # 不是项目文档或源码；非点名的依赖/产物目录仍走 EXCLUDED_DIRS。
        return name.startswith(".") or name in EXCLUDED_DIRS

    def _excluded(self, rel_parts: tuple[str, ...]) -> bool:
        if any(part.startswith(".") for part in rel_parts):
            return True
        return any(
            len(excl) <= len(rel_parts) and rel_parts[: len(excl)] == excl
            for excl in self.scan_excludes
        )

    def iter_files(self, suffixes: set[str], limit: int | None = None):
        """按稳定顺序遍历匹配文件。

        生产传感器默认完整扫描。调用方若为轻量路径显式设置预算，超限必须
        抛错而不是静默截断；部分证据不能支撑 fail-closed 的门禁结论。
        范围削减通过两类通用类别完成：点目录（工具状态）与 manifest
        `scan_excludes`（项目声明的数据目录）；两者都不把超限变成静默截断。
        """
        root = str(self.root)
        count = 0
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            rel_parts = (
                ()
                if rel_dir == "."
                else tuple(PurePosixPath(rel_dir.replace(os.sep, "/")).parts)
            )
            dirnames[:] = sorted(
                d
                for d in dirnames
                if not self._is_tool_state(d)
                and not self._excluded(rel_parts + (d,))
            )
            if self._excluded(rel_parts):
                continue
            for name in sorted(filenames):
                if Path(name).suffix in suffixes:
                    count += 1
                    if limit is not None and count > limit:
                        raise FileScanLimitExceeded(limit=limit, suffixes=suffixes)
                    yield Path(dirpath) / name

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

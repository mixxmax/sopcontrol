"""修复用 git worktree 隔离（B3 补完）。

自动修复者只在隔离目录改文件；主工作区默认不动，由 apply 显式合并回主树。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class WorktreeError(Exception):
    pass


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=120)


def ensure_git_repo(root: Path) -> None:
    if not (root / ".git").exists():
        raise WorktreeError(f"{root} 不是 git 仓库，无法创建 worktree")


def worktree_path(root: Path, task_id: str) -> Path:
    return Path(root) / ".sopcontrol" / "worktrees" / task_id


def create_repair_worktree(root: Path, task_id: str) -> Path:
    """在 .sopcontrol/worktrees/<task_id> 创建隔离工作树（基于 HEAD）。"""
    root = Path(root).resolve()
    ensure_git_repo(root)
    dest = worktree_path(root, task_id)
    if dest.exists():
        remove_repair_worktree(root, task_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # 未提交变更时 worktree add 仍可用当前 HEAD；隔离副本干净
    proc = _run(["git", "worktree", "add", "--detach", str(dest), "HEAD"], root)
    if proc.returncode != 0:
        raise WorktreeError(f"创建 worktree 失败: {proc.stderr.strip() or proc.stdout.strip()}")
    return dest


def remove_repair_worktree(root: Path, task_id: str) -> None:
    root = Path(root).resolve()
    dest = worktree_path(root, task_id)
    if not dest.exists():
        return
    _run(["git", "worktree", "remove", "--force", str(dest)], root)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    _run(["git", "worktree", "prune"], root)


def list_changed_files(work: Path) -> list[str]:
    """相对 work 根的已改/未跟踪文件。"""
    proc = _run(["git", "status", "--porcelain"], work)
    if proc.returncode != 0:
        return []
    out = []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        out.append(path)
    return out


def copy_paths_to_main(work: Path, main: Path, rel_paths: list[str]) -> list[str]:
    """把隔离树中的相对路径复制回主工作区。"""
    copied = []
    for rel in rel_paths:
        src = work / rel
        dst = main / rel
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)
    return copied

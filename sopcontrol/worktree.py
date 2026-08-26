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


def resolves_inside(base: Path, relpath: str) -> bool:
    """relpath 解析后是否仍落在 base 之内（symlink 逃逸检查，R8）。

    纯字符串前缀比对拦不住 symlink：允许写 `src/` 时，`src/link -> /etc` 让
    `src/link/passwd` 字面上完全合规，实际写的是仓库外的文件。这一层必须碰文件系统，
    所以放在采集边界，不放进 task.path_allowed（迁移门受纯函数宪法守卫）。

    末节点和每一层父目录都要查：只查父目录会漏掉「末节点自己就是 symlink」
    （`src/evil.py -> /etc/passwd`，copy2 跟着链接写到仓库外）；只 resolve 末节点
    又会漏掉「中间某一层是 symlink」。路径尚不存在（新建文件）时按最近的已存在祖先判断。

    悬空 symlink 要单独认：它 exists() 为假但确实会被写穿，所以先问 is_symlink()。
    """
    base = Path(base).resolve()
    target = base / relpath
    while True:
        if target.is_symlink() or target.exists():
            try:
                target.resolve().relative_to(base)
            except ValueError:
                return False
            return True
        parent = target.parent
        if parent == target:
            return False
        target = parent


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

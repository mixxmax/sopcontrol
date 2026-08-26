"""路径逃逸的三层守卫（RESIDUAL_RISKS R8）。

字符串前缀比对是范围控制的地基，而它有两个方向的失效，性质完全不同：

- allow-list 比对不上 → 多拒一个改动（fail-closed，最坏是误报，可接受）；
- deny-list 比对不上 → 直接放行（fail-open，信任根就此可写）。

所以这里的断言是不对称的：allow-list 保持大小写敏感，deny-list 一律大小写不敏感。
symlink 逃逸绕过全部字符串层，必须碰文件系统，测的是采集边界那一层。
"""
import builtins

import pytest

from sopcontrol.harness import (
    command_touches_controller,
    touches_protected_install,
    touches_protected_path,
)
from sopcontrol.task import is_controller_path, path_allowed
from sopcontrol.worktree import resolves_inside

# macOS / Windows 文件系统大小写不敏感：这些写的都是同一个信任根
CONTROLLER_DISGUISES = [
    ".sopcontrol/rules/registry.yaml",
    ".SOPCONTROL/rules/registry.yaml",
    ".SopControl/evidence/ledger.jsonl",
    "src/.SOPCONTROL/tasks/TASK-0001.yaml",  # 嵌套位置同样是控制器目录
]

NOT_CONTROLLER = [
    "src/app.py",
    "sopcontrol/task.py",          # 源码包不是状态目录
    ".sopcontrol-local/scratch",   # 前缀相同不等于同一个分量
    "docs/sopcontrol.md",
]


@pytest.mark.parametrize("relpath", CONTROLLER_DISGUISES)
def test_controller_path_detected_case_insensitively(relpath):
    assert is_controller_path(relpath), f"{relpath} 应判为控制器路径"
    assert path_allowed(relpath, [".sopcontrol", "src", ".SOPCONTROL"]) is False, (
        "即便契约把控制器目录列进 allowed_writes，也不得放行：信任根只能经 sopctl 变更"
    )


@pytest.mark.parametrize("relpath", NOT_CONTROLLER)
def test_non_controller_path_not_flagged(relpath):
    assert is_controller_path(relpath) is False, f"{relpath} 不该判为控制器路径"


def test_allow_list_stays_case_sensitive():
    """allow-list 不做大小写归一：归一化会把契约外的 SRC/ 放进 src 的范围（fail-open）。"""
    assert path_allowed("src/a.py", ["src"]) is True
    assert path_allowed("SRC/a.py", ["src"]) is False


def test_path_allowed_does_no_io(monkeypatch):
    """新增的控制器判定仍在纯函数一侧（迁移门受宪法守卫，见 test_task_gate）。"""
    def no_open(*args, **kwargs):
        raise AssertionError("范围判定不得做任何 I/O（宪法：纯函数）")

    monkeypatch.setattr(builtins, "open", no_open)
    assert path_allowed("src/a.py", ["src"]) is True
    assert path_allowed(".SOPCONTROL/x.yaml", ["src"]) is False


@pytest.mark.parametrize("file_path", CONTROLLER_DISGUISES)
def test_hook_write_guard_case_insensitive(file_path):
    assert touches_protected_path(file_path), f"写入 {file_path} 应被守卫认出"


def test_hook_install_guard_case_insensitive():
    assert touches_protected_install(".OpenCode/Plugins/SopControl/index.js")
    assert touches_protected_install(".claude/SETTINGS.JSON")
    assert touches_protected_install("src/app.py") is False


def test_bash_guard_case_insensitive():
    assert command_touches_controller("rm -rf .SOPCONTROL")
    assert command_touches_controller("cat > .SopControl/rules/registry.yaml")
    # 走 sopctl 是唯一的放行条件，大小写加固不能顺手改掉这个语义
    assert command_touches_controller("sopctl rule accept RULE-1") is False
    assert command_touches_controller("pytest -q") is False


def test_symlink_escape_rejected(tmp_path):
    """`src/link -> 外部` 让 src/link/passwd 字面完全合规，实际写在仓库外。"""
    base = tmp_path / "base"
    (base / "src").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "passwd").write_text("secret", encoding="utf-8")
    (base / "src" / "app.py").write_text("x = 1", encoding="utf-8")
    (base / "src" / "link").symlink_to(tmp_path / "outside")
    (base / "src" / "abs").symlink_to("/etc")

    assert resolves_inside(base, "src/link/passwd") is False
    assert resolves_inside(base, "src/abs/hosts") is False
    # 契约字符串层看不出区别——这正是需要第三层的理由
    assert path_allowed("src/link/passwd", ["src"]) is True


def test_symlinked_leaf_rejected(tmp_path):
    """末节点自己就是 symlink：copy2 跟着链接写，检查只看父目录就漏了。

    悬空链接（目标不存在）同样要拒：exists() 为假，但写入会创建目标文件。
    """
    base = tmp_path / "base"
    (base / "src").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "target.py").write_text("secret", encoding="utf-8")
    (base / "src" / "evil.py").symlink_to(tmp_path / "outside" / "target.py")
    (base / "src" / "dangling.py").symlink_to(tmp_path / "outside" / "nothere.py")

    assert resolves_inside(base, "src/evil.py") is False
    assert resolves_inside(base, "src/dangling.py") is False
    assert path_allowed("src/evil.py", ["src"]) is True


def test_symlink_check_allows_legitimate_paths(tmp_path):
    base = tmp_path / "base"
    (base / "src").mkdir(parents=True)
    (base / "src" / "app.py").write_text("x = 1", encoding="utf-8")

    assert resolves_inside(base, "src/app.py") is True
    assert resolves_inside(base, "src") is True
    # 新建文件的父目录还不存在，按最近的已存在祖先判断，不能一律拒
    assert resolves_inside(base, "src/new/deep/file.py") is True

"""真实使用修复：大仓扫描必须能声明排除项，点目录按工具状态处理。

JobsFlow 实测：14,443 个 .md（.codex-worktrees 9,565 / JobSearch_2026 3,712 /
.agents 883）触发 FileScanLimitExceeded，audit 与 gate 在整个仓库不可用。
修复语义：点目录默认不扫（git 生态惯例：点目录是工具状态）；
manifest `scan_excludes` 声明数据目录；两者都不改变"超限大声失败"的诚实语义。
"""
from pathlib import Path

import pytest

from sopcontrol.context import FileScanLimitExceeded, ProjectContext
def _make(root: Path, rel: str, content: str = "x") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _md_paths(root: Path, suffixes={".md"}, limit=500):
    ctx = ProjectContext(root)
    return sorted(ctx.iter_files(suffixes, limit=limit))


def test_dot_directories_are_pruned_as_tool_state(tmp_path):
    _make(tmp_path, "README.md")
    _make(tmp_path, ".codex-worktrees/w1/a.md")
    _make(tmp_path, ".agents/skills/b.md")
    _make(tmp_path, ".sopcontrol/evidence/c.md")

    found = _md_paths(tmp_path)

    assert found == [tmp_path / "README.md"]


def test_manifest_scan_excludes_remove_data_directories(tmp_path):
    _make(tmp_path, "docs/sop.md")
    _make(tmp_path, "JobSearch_2026/jobs/a.md")
    _make(tmp_path, "JobSearch_2026/deep/nested/b.md")
    _make(tmp_path, "05_Archive/old.md")
    (tmp_path / ".sopcontrol").mkdir(exist_ok=True)
    (tmp_path / ".sopcontrol/manifest.yaml").write_text(
        "scan_excludes:\n- JobSearch_2026\n- 05_Archive\n", encoding="utf-8"
    )

    found = _md_paths(tmp_path)

    assert found == [tmp_path / "docs/sop.md"]


def test_manifest_excludes_use_component_prefix_not_substring(tmp_path):
    _make(tmp_path, "JobSearch_2026_data/a.md")
    _make(tmp_path, "docs/x.md")
    (tmp_path / ".sopcontrol").mkdir(exist_ok=True)
    (tmp_path / ".sopcontrol/manifest.yaml").write_text(
        "scan_excludes:\n- JobSearch_2026\n", encoding="utf-8"
    )

    found = _md_paths(tmp_path)

    assert sorted(found) == [tmp_path / "JobSearch_2026_data/a.md", tmp_path / "docs/x.md"]


def test_invalid_scan_excludes_fail_closed(tmp_path):
    (tmp_path / ".sopcontrol").mkdir(exist_ok=True)
    (tmp_path / ".sopcontrol/manifest.yaml").write_text(
        "scan_excludes:\n- ../outside\n", encoding="utf-8"
    )
    _make(tmp_path, "a.md")

    with pytest.raises(ValueError, match="scan_excludes"):
        ctx = ProjectContext(tmp_path)
        list(ctx.iter_files({".md"}, limit=10))


def test_over_limit_without_excludes_still_fails_loud(tmp_path):
    for i in range(6):
        _make(tmp_path, f"docs/d{i}/a.md")

    ctx = ProjectContext(tmp_path)
    with pytest.raises(FileScanLimitExceeded):
        list(ctx.iter_files({".md"}, limit=5))


def test_sensors_can_still_mint_evidence_on_pruned_tree(tmp_path):
    """集成：排除生效后，传感器能在真树上正常铸证据（不空手、不崩）。"""
    _make(tmp_path, "docs/sop.md", "# 规则\n\n必须先预览。\n")
    _make(tmp_path, "JobSearch_2026/a.md", "数据")
    (tmp_path / ".sopcontrol").mkdir(exist_ok=True)
    (tmp_path / ".sopcontrol/manifest.yaml").write_text(
        "scan_excludes:\n- JobSearch_2026\n", encoding="utf-8"
    )

    from plugins.sensors.doc_scan import DocScanSensor

    ctx = ProjectContext(tmp_path)
    evidence = DocScanSensor().observe(ctx)

    assert evidence, "排除数据目录后真实文档应铸出证据"
    assert all(
        not Path(ev.subject).is_relative_to("JobSearch_2026") for ev in evidence
    )


def _git_repo(tmp_path):
    import subprocess

    root = tmp_path / "repo"
    root.mkdir()
    def git(*args):
        subprocess.run(
            ["git", "-C", str(root), *args],
            check=True, capture_output=True,
        )
    git("init", "-q")
    # 身份写进仓库本地 config：对环境变量与全局 gitconfig 污染免疫
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    git("commit", "-q", "--allow-empty", "-m", "base")
    return root, git


def test_git_mode_enumerates_tracked_untracked_and_respects_gitignore(tmp_path):
    root, git = _git_repo(tmp_path)
    _make(root, "docs/sop.md", "必须先预览")
    _make(root, "src/app.py", "x = 1")
    _make(root, "JobSearch_2026/data.md", "数据")
    _make(root, "ignored/generated.md", "生成物")
    _make(root, "untracked.md", "未跟踪但未忽略")
    (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "c1")

    found = _md_paths(root)

    assert root / "docs/sop.md" in found
    assert root / "JobSearch_2026/data.md" in found      # tracked 数据仍按声明排除与否由 manifest 决定
    assert root / "untracked.md" in found                # untracked-not-ignored 纳入
    assert root / "ignored/generated.md" not in found    # gitignore 由 git 回答


def test_git_mode_prunes_dot_dirs_even_when_tracked(tmp_path):
    root, git = _git_repo(tmp_path)
    _make(root, "docs/sop.md")
    _make(root, ".agents/skills/skill.md", "工具状态")
    (root / ".gitignore").write_text("", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "c1")

    found = _md_paths(root)

    assert root / "docs/sop.md" in found
    assert root / ".agents/skills/skill.md" not in found  # tracked 的点目录也是工具状态


def test_git_mode_over_limit_still_fails_loud(tmp_path):
    root, git = _git_repo(tmp_path)
    for i in range(6):
        _make(root, f"docs/d{i}/a.md")
    git("add", "-A")
    git("commit", "-qm", "c1")

    ctx = ProjectContext(root)
    with pytest.raises(FileScanLimitExceeded):
        list(ctx.iter_files({".md"}, limit=5))


def test_git_mode_manifest_excludes_still_apply(tmp_path):
    root, git = _git_repo(tmp_path)
    _make(root, "docs/sop.md")
    _make(root, "JobSearch_2026/data.md")
    (root / ".sopcontrol").mkdir(exist_ok=True)
    (root / ".sopcontrol/manifest.yaml").write_text(
        "scan_excludes:\n- JobSearch_2026\n", encoding="utf-8"
    )
    git("add", "-A")
    git("commit", "-qm", "c1")

    found = _md_paths(root)

    assert found == [root / "docs/sop.md"]


def test_scan_coverage_classifies_and_reports_complete(tmp_path):
    root, git = _git_repo(tmp_path)
    _make(root, "docs/sop.md")
    _make(root, ".agents/skill.md", "工具状态")
    _make(root, "JobSearch_2026/data.md")
    (root / ".sopcontrol").mkdir(exist_ok=True)
    (root / ".sopcontrol/manifest.yaml").write_text(
        "scan_excludes:\n- JobSearch_2026\n", encoding="utf-8"
    )
    git("add", "-A")
    git("commit", "-qm", "c1")

    ctx = ProjectContext(root)
    report = ctx.scan_coverage({".md"})

    assert report["mode"] == "git"
    assert report["complete"] is True
    assert report["eligible"] == 1
    assert report["pruned_tool_state"] == 1
    assert report["pruned_manifest"] == 1
    assert "git" in report["reason"]


def test_scan_coverage_walk_mode_reports_nongit(tmp_path):
    _make(tmp_path, "docs/a.md")

    report = ProjectContext(tmp_path).scan_coverage({".md"})

    assert report["mode"] == "walk"
    assert report["complete"] is True
    assert report["eligible"] == 1

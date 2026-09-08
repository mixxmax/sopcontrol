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

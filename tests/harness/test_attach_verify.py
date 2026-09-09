"""attach --verify（§5.4/§7）：真实穿透自检、四字段报告、JSON 输出。

§7.1 失败路径：探针未通过 → gap + safe_next_action（不是裸错误文本）；
§1.3：单表面 gap 不拖垮其余表面——逐表面独立判定。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sopcontrol.attach_verify import verify_attachment
from sopcontrol.cli import main


def _init_project(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    assert main(["init", str(path)]) == 0


def test_verify_reports_all_surfaces_verified_on_clean_project(tmp_path, monkeypatch):
    from sopcontrol.coverage_model import ProbeResult

    _init_project(tmp_path)
    monkeypatch.setattr(
        "sopcontrol.attach_verify.verify_surface",
        lambda root, surface: ProbeResult(
            surface=surface, passed=True, worktree_id="wt",
        ),
    )

    report = verify_attachment(tmp_path)

    assert report["schema_version"] == "1"
    assert set(report["verified"]) == {
        "filesystem_write", "filesystem_read", "shell", "search", "network",
        "browser", "database", "background",
    }
    assert report["gaps"] == []
    for item in report["surfaces"]:
        assert set(item) == {
            "surface", "state", "why", "safe_next_action", "user_input_required",
        }
        assert item["state"] == "verified"
        assert item["user_input_required"] is False


def test_verify_cli_json_and_gap_exit(tmp_path, capsys, monkeypatch):
    from sopcontrol.coverage_model import ProbeResult

    _init_project(tmp_path)
    monkeypatch.setattr(
        "sopcontrol.attach_verify.verify_surface",
        lambda root, surface: ProbeResult(
            surface=surface, passed=True, worktree_id="wt",
        ),
    )

    assert main(["attach", "--verify", "--json", str(tmp_path)]) == 0
    data = capsys.readouterr().out
    assert '"state": "verified"' in data


def test_verify_gap_reports_safe_next_action(tmp_path, monkeypatch):
    _init_project(tmp_path)
    import sopcontrol.attach_verify as av
    from sopcontrol.coverage_model import ProbeResult

    def failing_probe(root, surface):
        return ProbeResult(
            surface=surface, passed=False,
            detail="拦截链未生效", worktree_id="default",
        )

    monkeypatch.setattr(av, "verify_surface", failing_probe)

    report = verify_attachment(tmp_path)

    assert len(report["gaps"]) == len(report["surfaces"])
    for item in report["surfaces"]:
        assert item["state"] == "gap"
        assert item["safe_next_action"].startswith("sopctl coverage")
        assert item["user_input_required"] is False


def test_verify_cli_text_output_shows_gap_next_step(tmp_path, capsys, monkeypatch):
    _init_project(tmp_path)
    import sopcontrol.attach_verify as av
    from sopcontrol.coverage_model import ProbeResult

    monkeypatch.setattr(
        av, "verify_surface",
        lambda root, surface: ProbeResult(
            surface=surface, passed=False, detail="拦截链未生效", worktree_id="wt",
        ),
    )

    assert main(["attach", "--verify", str(tmp_path)]) == 2
    out = capsys.readouterr().out
    assert "gap" in out
    assert "sopctl coverage" in out

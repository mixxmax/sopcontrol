"""P2 切片 A：database/background 真实探针——无 adapter 时诚实 gap，不伪造 verified。"""
from __future__ import annotations

from pathlib import Path

from sopcontrol.attach_verify import _PROBE_SURFACES, verify_attachment
from sopcontrol.cli import main
from sopcontrol.coverage_probe import verify_surface


def _init_project(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    assert main(["init", str(path)]) == 0


def test_new_surfaces_registered_for_verify():
    assert "database" in _PROBE_SURFACES
    assert "background" in _PROBE_SURFACES
    assert "browser" in _PROBE_SURFACES


def test_database_background_probe_honest_gap_without_adapter(tmp_path):
    _init_project(tmp_path)
    for surface in ("database", "background", "browser"):
        result = verify_surface(tmp_path, surface)
        assert result.passed is False
        assert result.detail  # 非裸失败：带可行动的原因


def test_verify_report_marks_new_surfaces_gap_with_next_action(tmp_path):
    _init_project(tmp_path)
    report = verify_attachment(tmp_path)
    by_surface = {item["surface"]: item for item in report["surfaces"]}
    for surface in ("database", "background", "browser"):
        item = by_surface[surface]
        assert item["state"] == "gap"
        assert set(item) == {
            "surface", "state", "why", "safe_next_action", "user_input_required",
        }
        assert item["safe_next_action"]
        assert surface in report["gaps"]
    assert report["next_step"]

"""节能预算：doctor 默认不跑全仓 audit；投影/候选有硬上限。"""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

from sopcontrol.cli import main
from sopcontrol.energy import (
    CANDIDATES_WARN_THRESHOLD,
    PROJECTION_MAX_TOKENS,
    candidates_budget_warning,
    estimate_tokens,
    fit_projection_text,
    inventory_from_snapshot,
    sort_pending_by_energy,
)
from sopcontrol.growth import SpaceSnapshot, capture_space_snapshot

ROOT = Path(__file__).resolve().parents[2]


def test_estimate_and_fit_projection_budget():
    assert estimate_tokens("abcd") == 1
    soft = ["<!-- sopcontrol:start -->", "## 空间生长", "- a", "- b" * 200]
    # build oversized body
    lines = [
        "<!-- sopcontrol:start -->",
        "# SOP Control 规则投影（自动生成，勿手改）",
        "## 空间生长（无感观察；定型需人）",
    ]
    lines += [f"- noise {i} " + ("x" * 80) for i in range(120)]
    lines += ["## 硬约束", "- 不得直接读写", "<!-- sopcontrol:end -->"]
    text = "\n".join(lines) + "\n"
    assert estimate_tokens(text) > PROJECTION_MAX_TOKENS or text.count("\n") > 80
    fitted, trimmed = fit_projection_text(text)
    assert trimmed is True
    assert "节能：投影已截断" in fitted
    assert "<!-- sopcontrol:end -->" in fitted
    assert estimate_tokens(fitted) <= PROJECTION_MAX_TOKENS + 80  # warn line slack


def test_sort_pending_prefers_delete_over_register():
    items = [
        {"action": "register_rule", "candidate_id": "C1"},
        {"action": "delete_entry", "candidate_id": "C2"},
        {"action": "improve_entry", "candidate_id": "C3"},
    ]
    ordered = sort_pending_by_energy(items)
    assert [i["candidate_id"] for i in ordered] == ["C2", "C3", "C1"]


def test_candidates_budget_warning_threshold():
    assert candidates_budget_warning(CANDIDATES_WARN_THRESHOLD) is None
    assert "节能警告" in (candidates_budget_warning(CANDIDATES_WARN_THRESHOLD + 1) or "")


def test_doctor_light_does_not_call_inventory(tmp_path):
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    capture_space_snapshot(work, source="measure", persist=True, light=False)
    with patch("sopcontrol.inventory.build_entry_inventory") as mocked:
        mocked.side_effect = AssertionError("doctor light must not audit via inventory")
        assert main(["doctor", str(work)]) == 0
        mocked.assert_not_called()


def test_doctor_full_may_call_inventory(tmp_path, capsys):
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    assert main(["doctor", "--full", str(work)]) == 0
    out = capsys.readouterr().out
    assert "入口清单(全量)" in out
    assert "doctor: 全部通过（全量）" in out


def test_doctor_light_uses_snapshot_label(tmp_path, capsys):
    work = tmp_path / "work"
    shutil.copytree(ROOT / "corpus" / "fixtures" / "jobflow-preview", work)
    capture_space_snapshot(work, source="measure", persist=True, light=False)
    assert main(["doctor", str(work)]) == 0
    out = capsys.readouterr().out
    assert "入口清单(轻量" in out
    assert "doctor: 全部通过（轻量）" in out


def test_inventory_from_snapshot_shape():
    snap = SpaceSnapshot(bypass_open=2, parallel_state=1, source="measure")
    inv = inventory_from_snapshot(snap)
    assert inv is not None
    assert inv["delete_first_actions"] == 2
    assert inv["light"] is True


def test_fit_warning_stays_inside_managed_section():
    """截断警告必须落在真 SECTION_END 之前；落到标记后 = 写/查两条路径不一致，
    投影超预算后 project check 将永久 STALE（合并验收非阻断 1）。"""
    from sopcontrol.project import SECTION_END

    lines = [
        "<!-- sopcontrol:v1 -->",
        "# SOP Control 规则投影（自动生成，勿手改）",
        "## 空间生长（无感观察；定型需人）",
    ]
    lines += [f"- 观察明细 {i}" for i in range(60)]
    lines += ["## 何以至此"] + [f"- 编年明细 {i}" for i in range(60)]
    lines += ["## 硬约束", "- 不得直接读写或修改 `.sopcontrol/`", SECTION_END]
    text = "\n".join(lines) + "\n"

    fitted, trimmed = fit_projection_text(text)
    assert trimmed
    assert "节能：投影已截断" in fitted
    assert fitted.rstrip().endswith(SECTION_END)
    assert fitted.index("节能：投影已截断") < fitted.index(SECTION_END)

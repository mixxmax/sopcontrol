"""动态规则 P0a：§12.1 解析测试。"""
from __future__ import annotations

import pytest

from sopcontrol.cli import main
from sopcontrol.control_profile import (
    ProfileError,
    freeze_profile,
    load_frozen,
    normalize_profile,
    plan_digest,
)

BASE = {
    "profile_id": "run-material-quality",
    "scope": {"project": "current-project", "task": "TASK-1", "phase": "material-audit"},
    "checks": {"required": ["jd_fit"], "excluded": ["style_polish"]},
    "baseline": {"source_ref": "jd-snapshot", "generation_mode": "authoritative"},
    "repair": {"max_rounds": 1},
    "budget": {"max_audit_calls": 1, "max_repair_calls": 1},
}


def test_single_required_check_ok():
    p = normalize_profile(BASE)
    assert p.checks.required == ["jd_fit"]


def test_required_and_excluded_coexist():
    p = normalize_profile(BASE)
    assert "style_polish" in p.checks.excluded


def test_same_check_different_modes_per_dimension():
    data = dict(BASE, checks={
        "required": ["jd_fit", "factual_accuracy"],
        "excluded": ["wording_style"],
        "modes": {"jd_fit": "block", "factual_accuracy": "block",
                  "wording_style": "ignore"},
    })
    p = normalize_profile(data)
    assert p.checks.modes["jd_fit"] == "block"


def test_excluded_check_with_non_ignore_mode_rejected():
    data = dict(BASE, checks={
        "required": ["jd_fit"], "excluded": ["style_polish"],
        "modes": {"style_polish": "block"},
    })
    with pytest.raises(ProfileError):
        normalize_profile(data)


def test_required_excluded_overlap_rejected():
    data = dict(BASE, checks={"required": ["jd_fit"], "excluded": ["jd_fit"]})
    with pytest.raises(ProfileError):
        normalize_profile(data)


def test_baseline_mode_missing_or_illegal_rejected():
    bad = dict(BASE)
    bad["baseline"] = {"generation_mode": "whatever"}
    with pytest.raises(ProfileError):
        normalize_profile(bad)


def test_repair_budget_missing_negative_overcap():
    for rounds in (-1, 99):
        bad = dict(BASE, repair={"max_rounds": rounds})
        with pytest.raises(ProfileError):
            normalize_profile(bad)
    bad = dict(BASE, budget={"max_audit_calls": -1, "max_repair_calls": 1})
    with pytest.raises(ProfileError):
        normalize_profile(bad)


def test_same_profile_stable_digest(tmp_path):
    p1 = normalize_profile(BASE)
    p2 = normalize_profile(dict(BASE))
    assert plan_digest(p1, 1) == plan_digest(p2, 1)
    assert plan_digest(p1, 1) != plan_digest(p1, 2)  # revision 入 digest，防旧结果复用


def test_freeze_increments_and_is_immutable(tmp_path):
    normalize_profile(BASE)
    from sopcontrol.control_profile import save_draft

    save_draft(tmp_path, normalize_profile(BASE))
    f1 = freeze_profile(tmp_path, "run-material-quality")
    f2 = freeze_profile(tmp_path, "run-material-quality")
    assert (f1.revision, f2.revision) == (1, 2)
    assert load_frozen(tmp_path, "run-material-quality", 1).digest == f1.digest


def test_cli_create_freeze_show_roundtrip(tmp_path, capsys):
    yml = tmp_path / "p.yaml"
    import yaml

    yml.write_text(yaml.safe_dump(BASE), encoding="utf-8")
    assert main(["profile", "create", "--from", str(yml), "--path", str(tmp_path)]) == 0
    assert main(["profile", "freeze", "run-material-quality", "--path", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "digest=plan-" in out
    assert main(["profile", "show", "run-material-quality", "--revision", "1",
                 "--path", str(tmp_path)]) == 0
    assert "run-material-quality" in capsys.readouterr().out


def test_cli_create_rejects_conflict(tmp_path, capsys):
    yml = tmp_path / "bad.yaml"
    import yaml

    bad = dict(BASE, checks={"required": ["jd_fit"], "excluded": ["jd_fit"]})
    yml.write_text(yaml.safe_dump(bad), encoding="utf-8")
    assert main(["profile", "create", "--from", str(yml), "--path", str(tmp_path)]) == 2
    assert "重叠" in capsys.readouterr().err

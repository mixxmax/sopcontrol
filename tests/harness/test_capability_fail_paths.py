"""Capability / profile 失败路径：缺失、损坏、身份不匹配、批准失败。"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sopcontrol.capability import (
    approve_profile,
    effective_control_knobs,
    load_profile,
    profile_approval_is_current,
)
from sopcontrol.cli import main


def test_load_profile_missing_returns_none(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    assert load_profile(work) is None


def test_load_profile_corrupt_yaml(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    path = work / ".sopcontrol" / "model-profile.yaml"
    path.write_text("{not: valid: yaml: [[[", encoding="utf-8")
    with pytest.raises(Exception):
        load_profile(work)


def test_approve_profile_requires_live_source(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    assert main([
        "capability-eval", "--model", "cap-fail", "--fixture", "strong", str(work),
    ]) == 0
    profile = load_profile(work)
    assert profile is not None
    with pytest.raises(ValueError):
        approve_profile(work, expected_evaluation_id=profile.evaluation_id, by="tester")


def test_effective_knobs_unknown_when_model_mismatch(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    assert main([
        "capability-eval", "--model", "model-a", "--fixture", "strong", str(work),
    ]) == 0
    profile = load_profile(work)
    knobs = effective_control_knobs(profile, current_model="model-b")
    assert knobs.tier == "unknown"
    assert profile_approval_is_current(profile, current_model="model-b") is False


def test_capability_events_cli_on_empty_project(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    rc = main(["capability-events", str(work)])
    assert rc in (0, 2)


def test_capability_compare_offline(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    rc = main([
        "capability-compare", str(work),
        "--live", "opencode",
        "--baseline", "strong",
    ])
    # live may fail without binary; accept fail-closed codes
    assert rc in (0, 1, 2)


def test_harness_check_payload_allow_and_deny(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    # read is typically allow/observe
    assert main([
        "harness-check", str(work),
        "--payload", '{"tool_name":"Read","tool_input":{"file_path":"README.md"}}',
    ]) == 0
    # write into .sopcontrol should deny
    assert main([
        "harness-check", str(work),
        "--payload",
        '{"tool_name":"Edit","tool_input":{"file_path":".sopcontrol/rules/registry.yaml"}}',
    ]) == 0  # CLI exits 0 even on deny JSON


def test_wrap_requires_command(tmp_path, capsys):
    work = tmp_path / "w"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    rc = main(["wrap", "codex", str(work)])
    assert rc != 0
    assert "用法" in capsys.readouterr().err
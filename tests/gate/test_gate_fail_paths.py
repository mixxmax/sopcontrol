"""Gate / CLI 失败路径：审计异常 fail-closed；参数错误稳定退出码。"""
from __future__ import annotations

from pathlib import Path

import pytest

from sopcontrol.cli import main
from sopcontrol.cli_common import run_gate


def test_gate_blocks_when_audit_raises(tmp_path, monkeypatch, capsys):
    work = tmp_path / "proj"
    work.mkdir()
    assert main(["init", str(work)]) == 0

    def boom(*_a, **_k):
        raise RuntimeError("sensor exploded")

    monkeypatch.setattr("sopcontrol.cli_common.run_audit", boom)
    assert run_gate(work) == 1
    err = capsys.readouterr().err
    assert "fail-closed" in err
    assert "sensor exploded" in err or "RuntimeError" in err


def test_gate_cli_propagates_audit_failure(tmp_path, monkeypatch, capsys):
    work = tmp_path / "proj"
    work.mkdir()
    assert main(["init", str(work)]) == 0

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr("sopcontrol.cli_common.run_audit", boom)
    assert main(["gate", str(work)]) == 1
    assert "fail-closed" in capsys.readouterr().err


def test_doctor_unknown_flag_exits_nonzero():
    with pytest.raises(SystemExit) as exc:
        main(["doctor", "--not-a-real-flag"])
    assert exc.value.code != 0


def test_growth_unknown_subcommand_exits():
    with pytest.raises(SystemExit) as exc:
        main(["growth", "not-a-sub"])
    assert exc.value.code != 0

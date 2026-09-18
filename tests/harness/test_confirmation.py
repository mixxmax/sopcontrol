"""WP-C3：可信确认通道——绑定、一次性、防重放、防跨项目、自称标注。"""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest

from sopcontrol.cli import main
from sopcontrol.confirmation import (
    ConfirmationError,
    approve_confirmation,
    change_digest,
    request_confirmation,
    show_confirmation,
)


def _secret_file_for(rec, path) -> str:
    path.write_text(rec["secret_one_time"], encoding="utf-8")
    os.chmod(path, 0o600)
    return str(path)


def _request(tmp_path, **kw):
    assert main(["init", str(tmp_path)]) == 0
    base = {"kind": "rule-accept", "subject_id": "DR-1",
            "digest": change_digest("DR-1", "审计不扩范围"), "purpose": "t"}
    base.update(kw)
    return request_confirmation(tmp_path, **base)


def test_request_approve_verify_roundtrip(tmp_path):
    rec = _request(tmp_path)
    assert rec["consumed"] is False
    shown = show_confirmation(tmp_path, rec["confirmation_id"])
    assert shown["change_digest"] == rec["change_digest"]
    sf = _secret_file_for(rec, tmp_path / "s.key")
    approval = approve_confirmation(tmp_path, rec["confirmation_id"],
                                    secret_file=str(sf))
    assert approval["authority"] == "claimed"
    assert approval["human_presence"] == "UNPROVEN"
    assert show_confirmation(tmp_path, rec["confirmation_id"])["consumed"] is True


def test_replay_rejected(tmp_path):
    rec = _request(tmp_path)
    sf = _secret_file_for(rec, tmp_path / "s.key")
    approve_confirmation(tmp_path, rec["confirmation_id"], secret_file=str(sf))
    with pytest.raises(ConfirmationError, match="重放"):
        approve_confirmation(tmp_path, rec["confirmation_id"], secret_file=str(sf))


def test_wrong_digest_rejected(tmp_path):
    rec = _request(tmp_path)
    sf = _secret_file_for(rec, tmp_path / "s.key")
    with pytest.raises(ConfirmationError, match="摘要不一致"):
        approve_confirmation(tmp_path, rec["confirmation_id"], secret_file=str(sf),
                             expected_digest="chg-deadbeef")


def test_expired_rejected(tmp_path):
    rec = _request(tmp_path, ttl_seconds=1)
    sf = _secret_file_for(rec, tmp_path / "s.key")
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    with pytest.raises(ConfirmationError, match="批准失败"):
        approve_confirmation(tmp_path, rec["confirmation_id"], secret_file=str(sf),
                             now=future)


def test_cross_project_rejected(tmp_path):
    import tempfile
    from pathlib import Path

    rec = _request(tmp_path)
    sf = _secret_file_for(rec, tmp_path / "s.key")
    other = Path(tempfile.mkdtemp())
    assert main(["init", str(other)]) == 0
    with pytest.raises(ConfirmationError):
        approve_confirmation(other, rec["confirmation_id"], secret_file=str(sf),
                             expected_project_id="proj-other")


def test_plaintext_secret_and_wide_perms_rejected(tmp_path):
    rec = _request(tmp_path)
    with pytest.raises(ConfirmationError, match="secret-file"):
        approve_confirmation(tmp_path, rec["confirmation_id"], secret_file="")
    loose = tmp_path / "loose.key"
    loose.write_text("x", encoding="utf-8")
    os.chmod(loose, 0o644)
    with pytest.raises(ConfirmationError, match="权限过宽"):
        approve_confirmation(tmp_path, rec["confirmation_id"],
                             secret_file=str(loose))


def test_rule_add_without_confirmation_marks_claimed(tmp_path, capsys, monkeypatch):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    monkeypatch.chdir(work)
    assert main(["rule", "add", "--id", "C3-1", "--statement", "审计不扩范围",
                 "--status", "accepted", "--source-ref", "s"]) == 0
    out = capsys.readouterr().out
    assert "authority: claimed" in out and "UNPROVEN" in out


def test_rule_add_with_confirmation_consumes(tmp_path, capsys, monkeypatch):
    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    monkeypatch.chdir(work)
    digest = change_digest("C3-2", "审计不扩范围")
    assert main(["confirm", "request", "--kind", "rule-accept",
                 "--subject", "C3-2", "--digest", digest,
                 "--purpose", "t"]) == 0
    req = json.loads(capsys.readouterr().out.split("\n警告:")[0])
    sf = _secret_file_for(req, work / "s.key")
    assert main(["rule", "add", "--id", "C3-2", "--statement", "审计不扩范围",
                 "--status", "accepted", "--source-ref", "s",
                 "--confirmation-id", req["confirmation_id"],
                 "--secret-file", str(sf)]) == 0
    out = capsys.readouterr().out
    assert "确认凭据已消费" in out
    assert show_confirmation(work, req["confirmation_id"])["consumed"] is True


def test_maintainer_token_path_recorded(tmp_path, monkeypatch):
    rec = _request(tmp_path)
    sf = tmp_path / "m.key"
    secret = "maintainer-test-token"
    sf.write_text(secret, encoding="utf-8")
    os.chmod(sf, 0o600)
    monkeypatch.setenv("SOPCTL_MAINTAINER_TOKEN", secret)
    approval = approve_confirmation(tmp_path, rec["confirmation_id"],
                                    secret_file=str(sf))
    assert approval["approved_via"] == "maintainer-token"
    assert approval["authority"] == "claimed"

"""WP-C3：可信确认通道——统一原语之上的绑定层（有效期/项目/摘要）。

底层一次性凭据复用 learning.py（全仓唯一确认原语）；本层补齐通用权威变更
所需的绑定。secret 经测试 helper 读取（测试专用通道，CLI 永不自动读）。
"""
from __future__ import annotations

import json
import os
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
from sopcontrol.learning import read_learning_confirmation_secret


def _request(tmp_path, **kw):
    assert main(["init", str(tmp_path)]) == 0
    base = {"kind": "rule-accept", "subject_id": "DR-1",
            "digest": change_digest("DR-1", "审计不扩范围"), "purpose": "t"}
    base.update(kw)
    return request_confirmation(tmp_path, **base)


def _secret(tmp_path, confirmation_id: str, path_name: str = "s.key") -> str:
    p = tmp_path / path_name
    p.write_text(read_learning_confirmation_secret(tmp_path, confirmation_id),
                 encoding="utf-8")
    os.chmod(p, 0o600)
    return str(p)


def test_request_approve_verify_roundtrip(tmp_path):
    rec = _request(tmp_path)
    assert rec["consumed"] is False
    assert "secret_one_time" not in rec  # secret 永不进返回值
    shown = show_confirmation(tmp_path, rec["confirmation_id"])
    assert shown["change_digest"] == rec["change_digest"]
    sf = _secret(tmp_path, rec["confirmation_id"])
    approval = approve_confirmation(tmp_path, rec["confirmation_id"],
                                    secret_file=sf)
    assert approval["authority"] == "claimed"
    assert approval["human_presence"] == "UNPROVEN"
    assert show_confirmation(tmp_path, rec["confirmation_id"])["consumed"] is True


def test_replay_rejected(tmp_path):
    rec = _request(tmp_path)
    sf = _secret(tmp_path, rec["confirmation_id"])
    approve_confirmation(tmp_path, rec["confirmation_id"], secret_file=sf)
    with pytest.raises(ConfirmationError, match="重放"):
        approve_confirmation(tmp_path, rec["confirmation_id"], secret_file=sf)


def test_wrong_digest_rejected(tmp_path):
    rec = _request(tmp_path)
    sf = _secret(tmp_path, rec["confirmation_id"])
    with pytest.raises(ConfirmationError, match="摘要不一致"):
        approve_confirmation(tmp_path, rec["confirmation_id"], secret_file=sf,
                             expected_digest="chg-deadbeef")


def test_expired_rejected(tmp_path):
    rec = _request(tmp_path, ttl_seconds=1)
    sf = _secret(tmp_path, rec["confirmation_id"])
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    with pytest.raises(ConfirmationError, match="过期"):
        approve_confirmation(tmp_path, rec["confirmation_id"], secret_file=sf,
                             now=future)


def test_cross_project_rejected(tmp_path):
    import tempfile
    from pathlib import Path

    rec = _request(tmp_path)
    sf = _secret(tmp_path, rec["confirmation_id"])
    other = Path(tempfile.mkdtemp())
    assert main(["init", str(other)]) == 0
    with pytest.raises(ConfirmationError):
        approve_confirmation(other, rec["confirmation_id"], secret_file=sf,
                             expected_project_id="proj-other")


def test_plaintext_secret_and_wide_perms_rejected(tmp_path):
    rec = _request(tmp_path)
    with pytest.raises(ConfirmationError, match="secret-file|secret"):
        approve_confirmation(tmp_path, rec["confirmation_id"], secret_file="")
    loose = tmp_path / "loose.key"
    loose.write_text("x", encoding="utf-8")
    os.chmod(loose, 0o644)
    with pytest.raises(ConfirmationError, match="权限过宽"):
        approve_confirmation(tmp_path, rec["confirmation_id"],
                             secret_file=str(loose))


def test_rule_add_without_confirmation_refused_zero_write(tmp_path, capsys, monkeypatch):
    """P0-1：无确认凭据的 accepted 写入必须拒绝，且零写入（原子性）。"""
    from sopcontrol.registry import Registry

    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    monkeypatch.chdir(work)
    assert main(["rule", "add", "--id", "C3-1", "--statement", "审计不扩范围",
                 "--status", "accepted", "--source-ref", "s"]) == 2
    assert "确认凭据" in capsys.readouterr().err
    rules = Registry(work / ".sopcontrol" / "rules" / "registry.yaml").load()
    assert [r.rule_id for r in rules] == []


def test_rule_add_with_bad_confirmation_zero_write(tmp_path, capsys, monkeypatch):
    """P0-1：错误凭据同样零写入（先验后写，无需回滚）。"""
    from sopcontrol.registry import Registry

    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    monkeypatch.chdir(work)
    digest = change_digest("C3-9", "审计不扩范围")
    assert main(["confirm", "request", "--kind", "rule-accept",
                 "--subject", "C3-9", "--digest", digest,
                 "--purpose", "t"]) == 0
    capsys.readouterr()
    assert main(["rule", "add", "--id", "C3-9", "--statement", "审计不扩范围",
                 "--status", "accepted", "--source-ref", "s",
                 "--confirmation-id", "lconf-deadbeef",
                 "--secret-file", str(work / "s.key")]) == 2
    rules = Registry(work / ".sopcontrol" / "rules" / "registry.yaml").load()
    assert [r.rule_id for r in rules] == []


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
    out = capsys.readouterr().out
    req = json.loads(out.split("\n下一步:")[0] if "\n下一步:" in out else out)
    assert "secret_one_time" not in req
    sf = _secret(work, req["confirmation_id"], "s.key")
    assert main(["rule", "add", "--id", "C3-2", "--statement", "审计不扩范围",
                 "--status", "accepted", "--source-ref", "s",
                 "--confirmation-id", req["confirmation_id"],
                 "--secret-file", sf]) == 0
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


def test_rule_accept_cli_requires_confirmation(tmp_path, capsys, monkeypatch):
    """P0-1：rule accept 同门——无凭据拒绝且不迁移，有凭据才接受。"""
    from sopcontrol.learning import read_learning_confirmation_secret
    from sopcontrol.registry import Registry

    work = tmp_path / "p"
    work.mkdir()
    assert main(["init", str(work)]) == 0
    capsys.readouterr()
    monkeypatch.chdir(work)
    assert main(["rule", "add", "--id", "C3-A", "--statement", "审计不扩范围",
                 "--source-ref", "s"]) == 0
    capsys.readouterr()
    assert main(["rule", "accept", "C3-A"]) == 2
    reg = Registry(work / ".sopcontrol" / "rules" / "registry.yaml")
    assert reg.load()[0].status.value == "proposed"
    digest = change_digest("C3-A", "审计不扩范围")
    rec = request_confirmation(work, kind="rule-accept", subject_id="C3-A",
                               digest=digest, purpose="t")
    secret = read_learning_confirmation_secret(work, rec["confirmation_id"])
    assert main(["rule", "accept", "C3-A",
                 "--confirmation-id", rec["confirmation_id"],
                 f"--confirmation-secret={secret}"]) == 0
    assert reg.load()[0].status.value == "accepted"

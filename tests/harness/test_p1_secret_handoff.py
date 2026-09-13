"""§10.5 必须添加的反例测试（Batch 5: Secret Handoff、脱敏和失败关闭）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sopcontrol.bridge import (
    _scrub,
    challenge_admission,
    run_bridge,
)
from sopcontrol.bridge_scaffold import install_scaffold


def _helper_py_child(script_content: str, tmp_path: Path) -> Path:
    script = tmp_path / "child_test.py"
    script.write_text(script_content, encoding="utf-8")
    script.chmod(0o755)
    return script


def test_handoff_read_error_blocks_before_child_start(tmp_path, monkeypatch):
    # handoff 读取失败时必须立即 fail-closed，绝不能启动子进程
    sentinel = tmp_path / "child_ran.sentinel"
    child = _helper_py_child(
        f"import pathlib\npathlib.Path({repr(str(sentinel))}).write_text('ran')\n",
        tmp_path,
    )

    # 模拟 handoff 写入损坏的 JSON
    import sopcontrol.bridge as bridge_mod
    orig_write = bridge_mod._write_ticket_handoff

    def bad_write(root, ticket, op_id, **kw):
        path, tid = orig_write(root, ticket, op_id, **kw)
        Path(path).write_text("corrupted json {", encoding="utf-8")
        return path, tid

    monkeypatch.setattr(bridge_mod, "_write_ticket_handoff", bad_write)

    receipt = run_bridge(
        tmp_path,
        integration_id="scan.cli",
        action="network.scan",
        argv=[sys.executable, str(child)],
        side_effect="network_request",
    )

    assert receipt["executed"] is False
    assert "handoff" in receipt.get("error", "").lower() or "fail-closed" in receipt.get("error", "").lower()
    # 子进程绝对不能运行
    assert not sentinel.exists()


def test_child_printing_full_secret_is_scrubbed(tmp_path):
    # 子进程打印完整 secret，输出和 receipt 必须脱敏
    child = _helper_py_child(
        """
import os, json, sys
hf = os.environ.get('SOPCTL_TICKET_FILE')
secret = json.loads(open(hf).read())['secret']
print(f"SECRET_OUTPUT:{secret}")
sys.exit(0)
""",
        tmp_path,
    )

    receipt = run_bridge(
        tmp_path,
        integration_id="scan.cli",
        action="network.scan",
        argv=[sys.executable, str(child)],
        side_effect="network_request",
    )

    # 从 receipt 提取被脱敏后的输出
    stdout = receipt["stdout_tail"]
    assert "SECRET_OUTPUT:" in stdout
    # 任何形似 raw secret 的内容都不能存在于输出
    assert "***" in stdout


def test_child_printing_arbitrary_secret_fragment_is_scrubbed(tmp_path):
    # 子进程在任意非固定步长 offset 处切片打印 secret 片段（例如 length 15, offset 7）
    # 必须脱敏，不能只检查固定 12/16/24 步长
    child = _helper_py_child(
        """
import os, json, sys
hf = os.environ.get('SOPCTL_TICKET_FILE')
secret = json.loads(open(hf).read())['secret']
frag = secret[7:22]
print(f"ARBITRARY_FRAG:{frag}")
sys.exit(0)
""",
        tmp_path,
    )

    receipt = run_bridge(
        tmp_path,
        integration_id="scan.cli",
        action="network.scan",
        argv=[sys.executable, str(child)],
        side_effect="network_request",
    )

    stdout = receipt["stdout_tail"]
    assert "ARBITRARY_FRAG:" in stdout
    # 片段被脱敏为 ***
    assert "***" in stdout
    assert "ARBITRARY_FRAG:***" in stdout


def test_json_escaped_secret_is_scrubbed():
    secret = "sec_test_secret_1234567890abcdef"
    raw = json.dumps({"token": secret})
    scrubbed = _scrub(raw, [secret])
    assert secret not in scrubbed
    assert "***" in scrubbed


def test_url_encoded_secret_is_scrubbed():
    secret = "sec/test+secret=1234567890abcdef"
    import urllib.parse
    encoded = urllib.parse.quote(secret, safe="")
    scrubbed = _scrub(f"url={encoded}", [secret])
    assert encoded not in scrubbed
    assert "***" in scrubbed


def test_secret_never_enters_receipt(tmp_path):
    child = _helper_py_child(
        """
import os, json, sys
hf = os.environ.get('SOPCTL_TICKET_FILE')
secret = json.loads(open(hf).read())['secret']
print(f"LEAK_STDOUT:{secret}")
sys.stderr.write(f"LEAK_STDERR:{secret}\\n")
sys.exit(0)
""",
        tmp_path,
    )

    # 预先获取签发的 ticket secret 供测试断言比对
    issued_secret = None
    import sopcontrol.bridge as bridge_mod
    orig_write = bridge_mod._write_ticket_handoff

    def grab_write(root, ticket, op_id, **kw):
        nonlocal issued_secret
        issued_secret = ticket.secret
        return orig_write(root, ticket, op_id, **kw)

    bridge_mod._write_ticket_handoff = grab_write
    try:
        receipt = run_bridge(
            tmp_path,
            integration_id="scan.cli",
            action="network.scan",
            argv=[sys.executable, str(child)],
            side_effect="network_request",
        )
    finally:
        bridge_mod._write_ticket_handoff = orig_write

    assert issued_secret is not None
    receipt_str = json.dumps(receipt)
    assert issued_secret not in receipt_str
    # 任意大于等于 8 字符的连续片段都不能在 receipt 中
    for i in range(len(issued_secret) - 7):
        assert issued_secret[i:i + 8] not in receipt_str


def test_secret_never_enters_error_text(tmp_path):
    # 当发生错误时，error 文本中不能包含 secret
    child = _helper_py_child(
        """
import os, json, sys
hf = os.environ.get('SOPCTL_TICKET_FILE')
secret = json.loads(open(hf).read())['secret']
sys.stderr.write(f"FATAL_ERROR_WITH_SECRET:{secret}\\n")
sys.exit(1)
""",
        tmp_path,
    )

    issued_secret = None
    import sopcontrol.bridge as bridge_mod
    orig_write = bridge_mod._write_ticket_handoff

    def grab_write(root, ticket, op_id, **kw):
        nonlocal issued_secret
        issued_secret = ticket.secret
        return orig_write(root, ticket, op_id, **kw)

    bridge_mod._write_ticket_handoff = grab_write
    try:
        receipt = run_bridge(
            tmp_path,
            integration_id="scan.cli",
            action="network.scan",
            argv=[sys.executable, str(child)],
            side_effect="network_request",
        )
    finally:
        bridge_mod._write_ticket_handoff = orig_write

    assert issued_secret is not None
    err = receipt.get("error", "") + receipt.get("stderr_tail", "")
    assert issued_secret not in err
    for i in range(len(issued_secret) - 7):
        assert issued_secret[i:i + 8] not in err


def test_success_handoff_is_removed_after_scrub(tmp_path, monkeypatch):
    # 执行成功后，handoff 文件必须被清理
    info = install_scaffold(
        tmp_path,
        name="py-ok",
        lang="python",
        integration_id="scan.cli",
        action="network.scan",
        command=["echo", "success"],
        side_effect="network_request",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd())
    monkeypatch.setattr(os, "environ", env)

    receipt = run_bridge(
        tmp_path,
        integration_id="scan.cli",
        action="network.scan",
        argv=[sys.executable, info["file"]],
        side_effect="network_request",
    )
    # handoff 文件必须不存在
    handoff_dir = tmp_path / ".sopcontrol-local" / "tickets" / ".handoff"
    if handoff_dir.exists():
        assert list(handoff_dir.glob("*.json")) == []


def test_failure_handoff_is_cleaned(tmp_path):
    # 即使子进程执行失败，最外层也必须清理 handoff 文件
    child = _helper_py_child("import sys; sys.exit(42)\n", tmp_path)
    receipt = run_bridge(
        tmp_path,
        integration_id="scan.cli",
        action="network.scan",
        argv=[sys.executable, str(child)],
        side_effect="network_request",
    )
    assert receipt["exit_code"] == 42
    handoff_dir = tmp_path / ".sopcontrol-local" / "tickets" / ".handoff"
    if handoff_dir.exists():
        assert list(handoff_dir.glob("*.json")) == []


def test_subprocess_start_failure_returns_structured_receipt(tmp_path):
    # 当子进程启动失败（例如可执行文件不存在），必须返回结构化 receipt，不得抛出未捕获异常
    receipt = run_bridge(
        tmp_path,
        integration_id="scan.cli",
        action="network.scan",
        argv=["/nonexistent/path/to/binary_12345", "arg1"],
        side_effect="network_request",
    )
    assert isinstance(receipt, dict)
    assert receipt["executed"] is False
    assert "error" in receipt
    assert "not found" in receipt["error"].lower() or "failed" in receipt["error"].lower() or "no such file" in receipt["error"].lower()


def test_timeout_output_is_scrubbed(tmp_path, monkeypatch):
    # 超时发生时，不得抛出未捕获异常，并且已产生的输出必须完成脱敏
    child = _helper_py_child(
        """
import os, json, sys, time
hf = os.environ.get('SOPCTL_TICKET_FILE')
secret = json.loads(open(hf).read())['secret']
print(f"BEFORE_SLEEP_SECRET:{secret}", flush=True)
time.sleep(10)
""",
        tmp_path,
    )

    issued_secret = None
    import sopcontrol.bridge as bridge_mod
    orig_write = bridge_mod._write_ticket_handoff

    def grab_write(root, ticket, op_id, **kw):
        nonlocal issued_secret
        issued_secret = ticket.secret
        return orig_write(root, ticket, op_id, **kw)

    bridge_mod._write_ticket_handoff = grab_write

    # 临时将 subprocess.run 的 timeout 缩短，用于触发超时
    orig_subproc_run = subprocess.run

    def short_run(*args, **kwargs):
        kwargs["timeout"] = 0.5
        return orig_subproc_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", short_run)

    try:
        receipt = run_bridge(
            tmp_path,
            integration_id="scan.cli",
            action="network.scan",
            argv=[sys.executable, str(child)],
            side_effect="network_request",
        )
    finally:
        bridge_mod._write_ticket_handoff = orig_write

    assert receipt["executed"] is False
    assert "timeout" in receipt.get("error", "").lower()
    assert issued_secret is not None
    assert issued_secret not in receipt.get("stdout_tail", "")
    assert issued_secret not in receipt.get("stderr_tail", "")
    assert issued_secret not in json.dumps(receipt)


def _fixed_ticket(ticket_id):
    from datetime import datetime, timedelta, timezone

    from sopcontrol.tickets import CapabilityTicket

    return CapabilityTicket(
        ticket_id=ticket_id, secret="s" * 40,
        project_id="", worktree_id="default",
        action="network.scan", input_fingerprint="fp",
        allowed_side_effects=["network_request"],
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )


def test_handoff_never_overwrites_existing_file(tmp_path):
    # §13.1（R-08）：独占创建——目标已存在时拒绝，内容原样保留
    from sopcontrol.bridge import _write_ticket_handoff

    d = tmp_path / ".sopcontrol-local" / "tickets" / ".handoff"
    d.mkdir(parents=True)
    path = d / "tkt-fixed.json"
    path.write_text('{"sentinel": true}', encoding="utf-8")
    ticket = _fixed_ticket("tkt-fixed")
    with pytest.raises(OSError):
        _write_ticket_handoff(tmp_path, ticket, "op-1")
    assert json.loads(path.read_text(encoding="utf-8")) == {"sentinel": True}


def test_handoff_does_not_follow_symlink(tmp_path):
    # §13.1（R-08）：目标为 symlink 时不跟随，外部文件不被写入
    from sopcontrol.bridge import _write_ticket_handoff

    d = tmp_path / ".sopcontrol-local" / "tickets" / ".handoff"
    d.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    try:
        (d / "tkt-sym.json").symlink_to(outside)
    except OSError:
        pytest.skip("平台不支持 symlink")
    ticket = _fixed_ticket("tkt-sym")
    with pytest.raises(OSError):
        _write_ticket_handoff(tmp_path, ticket, "op-1")
    assert outside.read_text(encoding="utf-8") == "outside"


def test_challenge_handoff_is_0600_and_valid_json(tmp_path):
    # 正向（公开入口）：challenge 落盘的 handoff 是 0600、合法 JSON、含 secret
    import stat as _stat

    issued = challenge_admission(
        tmp_path, integration_id="scan.cli", action="network.scan",
        argv=["curl", "https://example.invalid"], side_effect="network_request",
    )
    p = Path(issued["handoff"])
    assert p.stat().st_mode & 0o777 == 0o600
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["secret"]
    assert data["operation_id"] == issued["operation_id"]
    assert _stat.S_ISREG(p.lstat().st_mode)

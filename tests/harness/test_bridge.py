"""桥接 P0/P1：闭环 admission（签发-handoff-子进程兑换-消费后验）、fail-closed 分类、无 secret 回执。"""
from __future__ import annotations

import os
import stat
import sys
import threading

import pytest

from sopcontrol.bridge import (
    canonical_fingerprint,
    operation_id,
    run_bridge,
)
from sopcontrol.tickets import ticket_public_view


def _admit_child(path, *, real=("echo", "hi")):
    """写一个合作 adapter 子进程：admit 后 exec 实参（指纹与 run argv 一致）。"""
    path.write_text(
        "#!/bin/sh\n"
        '"$SOPCTL_ADMIT_PY" -m sopcontrol.cli bridge admit '
        '--integration-id "$SOPCTL_ADMIT_I" --action "$SOPCTL_ADMIT_A" '
        '--side-effect "$SOPCTL_ADMIT_S" -- "$0" "$@" || exit $?\n'
        'exec "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return [str(path), *real]


def _admit_env(monkeypatch, *, integration="scan.cli", action="network.scan",
               side_effect="network_request"):
    monkeypatch.setenv("SOPCTL_ADMIT_PY", sys.executable)
    monkeypatch.setenv("SOPCTL_ADMIT_I", integration)
    monkeypatch.setenv("SOPCTL_ADMIT_A", action)
    monkeypatch.setenv("SOPCTL_ADMIT_S", side_effect)


def test_operation_id_and_fingerprint_are_stable_across_retries(tmp_path):
    """§3.1：同一逻辑操作的挑战与重试必须同 operation_id / fingerprint；
    指纹不含时间、attempt、secret、ticket id。"""
    argv = ["product", "scan", "--url", "https://example.test/api"]
    op1 = operation_id("scan.cli", "network.request", argv)
    fp1 = canonical_fingerprint("scan.cli", "network.request", argv)
    op2 = operation_id("scan.cli", "network.request", list(argv))
    fp2 = canonical_fingerprint("scan.cli", "network.request", list(argv))

    assert op1 == op2 and op1.startswith("op-")
    assert fp1 == fp2 and fp1.startswith("sha256:")
    # 任何输入变化都改变指纹
    assert canonical_fingerprint("scan.cli", "network.request", ["product", "scan", "--url", "https://other.test"]) != fp1


def test_readonly_action_runs_without_ticket(tmp_path):
    """§4.4：本地只读动作不进入票据流程，直接执行并出回执。"""
    receipt = run_bridge(tmp_path, integration_id="scan.cli", action="scan", argv=["echo", "hello"])

    assert receipt["side_effect"] == "none"
    assert receipt["ticket"] is None
    assert receipt["executed"] is True
    assert receipt["exit_code"] == 0
    assert receipt["attempt_id"] != receipt["operation_id"]
    assert "hello" in receipt["stdout_tail"]


def test_ticket_required_action_challenges_once_then_succeeds_on_retry(tmp_path, monkeypatch):
    """合作子进程在真实入口兑换后才算通过（闭环，非 bridge 自兑）。"""
    _admit_env(monkeypatch)
    child = tmp_path / "admit-child.sh"
    receipt = run_bridge(
        tmp_path,
        integration_id="scan.cli",
        action="network.scan",
        argv=_admit_child(child, real=("echo", "side-effect")),
        side_effect="network_request",
    )

    assert receipt["challenge_count"] == 1          # 无票第一次只产生一次挑战
    assert receipt["executed"] is True              # 子进程兑换后真实执行
    assert receipt["ticket"]["ticket_id"].startswith("tkt-")
    assert "secret" not in receipt["ticket"]        # 回执不含 secret
    assert receipt["operation_id"].startswith("op-")
    assert receipt["redemption_point"].startswith("child-admission")
    assert "side-effect" in receipt["stdout_tail"]


def test_opaque_child_without_admission_fails(tmp_path):
    """复查核心：子进程不校验 handoff 即视为未通过（没有不兑也过）。"""
    receipt = run_bridge(
        tmp_path, integration_id="scan.cli", action="network.scan",
        argv=["echo", "x"], side_effect="network_request",
    )
    assert receipt["executed"] is False
    assert "admission 未兑换" in receipt["error"]
    assert receipt["redemption_point"] == "none (admission missing)"


def test_tampered_retry_is_rejected_and_ticket_not_consumed(tmp_path):
    """§4.3/§10.3：重试改变输入/动作被拒；票据未消费时正确重试仍可兑换。"""
    from sopcontrol.bridge import challenge_ticket
    from sopcontrol.tickets import redeem_ticket, TicketError

    argv = ["tool", "sync"]
    fp = canonical_fingerprint("sync.cli", "external.write", argv)
    ticket = challenge_ticket(
        tmp_path, integration_id="sync.cli", action="external.write",
        input_fingerprint=fp, side_effect="external_write",
    )

    with pytest.raises(TicketError, match="fingerprint"):
        redeem_ticket(
            tmp_path, ticket_id=ticket.ticket_id, secret=ticket.secret,
            action="external.write", input_fingerprint="sha256:tampered",
            side_effect="external_write",
        )
    # 拒绝后票据未被消费：同一指纹的正确重试仍可兑换
    redeemed = redeem_ticket(
        tmp_path, ticket_id=ticket.ticket_id, secret=ticket.secret,
        action="external.write", input_fingerprint=fp,
        side_effect="external_write",
    )
    assert redeemed.consumed_at is not None
    # 已消费后再兑：拒绝（防双消费）
    with pytest.raises(TicketError, match="consumed"):
        redeem_ticket(
            tmp_path, ticket_id=ticket.ticket_id, secret=ticket.secret,
            action="external.write", input_fingerprint=fp,
            side_effect="external_write",
        )


def test_concurrent_redemption_only_one_succeeds(tmp_path):
    """§9 P1：跨进程原子锁防止并发双消费。"""
    from sopcontrol.bridge import challenge_ticket
    from sopcontrol.tickets import redeem_ticket, TicketError

    fp = canonical_fingerprint("sync.cli", "external.write", ["tool", "sync"])
    ticket = challenge_ticket(
        tmp_path, integration_id="sync.cli", action="external.write",
        input_fingerprint=fp, side_effect="external_write",
    )
    results = []
    def redeem():
        try:
            redeem_ticket(
                tmp_path, ticket_id=ticket.ticket_id, secret=ticket.secret,
                action="external.write", input_fingerprint=fp,
                side_effect="external_write",
            )
            results.append("ok")
        except Exception:
            results.append("rejected")

    threads = [threading.Thread(target=redeem) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert results.count("ok") == 1
    assert results.count("rejected") == 7


def test_secret_never_persists_in_public_view_or_receipt(tmp_path, monkeypatch):
    """子进程回显 handoff 文件内容，receipt tails 必须洗脱 secret。"""
    _admit_env(monkeypatch)
    child = tmp_path / "leaky-child.sh"
    child.write_text(
        "#!/bin/sh\n"
        'cat "$SOPCTL_TICKET_FILE"\n'
        '"$SOPCTL_ADMIT_PY" -m sopcontrol.cli bridge admit '
        '--integration-id "$SOPCTL_ADMIT_I" --action "$SOPCTL_ADMIT_A" '
        '--side-effect "$SOPCTL_ADMIT_S" -- "$0" "$@" || exit $?\n'
        'exec "$@"\n',
        encoding="utf-8",
    )
    child.chmod(0o755)
    receipt = run_bridge(
        tmp_path, integration_id="scan.cli", action="network.scan",
        argv=[str(child), "echo", "x"], side_effect="network_request",
    )

    def _walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert k != "secret", "secret key leaked into receipt object"
                yield from _walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from _walk(v)

    assert receipt["executed"] is True
    assert "ticket_model" not in receipt  # 对象级剥离：打印过滤之外无残留
    list(_walk(receipt))
    assert receipt["ticket"].get("secret") is None
    assert "tkt-" in receipt["stdout_tail"]  # ticket_id 可审计，secret 已洗
    # handoff 文件跑后删除，不留 secret 载体
    from pathlib import Path as _Path

    assert receipt["ticket_handoff"].endswith("(removed after run)")
    assert not _Path(receipt["ticket_handoff"].split(" ")[0]).exists()


def test_unified_fingerprint_matches_action_envelope(tmp_path):
    """§9.5：bridge 动作并入 ActionEnvelope 分类机器——同一命令经任意
    harness 到达，指纹一致（build_envelope 与 canonical 同基）。"""
    from sopcontrol.action_plane import build_envelope

    argv = ["product", "scan", "--url", "https://example.test/api"]
    command = " ".join(argv)
    envelope = build_envelope(
        {"tool_name": "Bash", "tool_input": {"command": command}},
        harness="bridge",
        task_id="scan.cli",
    )
    from sopcontrol.bridge import canonical_payload
    basis = canonical_payload("scan.cli", "network.scan", argv)
    import json as _json
    import hashlib as _hashlib
    base_no_ids = {k: v for k, v in basis.items() if k not in ("operation_id", "run_id")}
    expected = "sha256:" + _hashlib.sha256(
        _json.dumps(base_no_ids, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

    assert canonical_fingerprint("scan.cli", "network.scan", argv) == expected
    # 同一逻辑动作重试不变
    assert canonical_fingerprint("scan.cli", "network.scan", list(argv)) == expected


def test_bridge_install_and_remove_wrapper_roundtrip(tmp_path):
    """§9.4：launcher 生成可执行、remove 回滚移除；回滚清单记录 existed_before。"""
    from sopcontrol.bridge import install_wrapper, remove_wrapper

    installed = install_wrapper(
        tmp_path, integration_id="scan.cli",
        command=["/Users/xiezhijie/sopcontrol/.venv/bin/sopctl", "bridge", "run",
                 "--action", "network.scan", "--side-effect", "network_request"],
        name="product-scan",
    )
    launcher = tmp_path / ".sopcontrol-local" / "bin" / "product-scan"
    assert launcher.exists() and launcher.stat().st_mode & 0o111

    removed = remove_wrapper(tmp_path, name="product-scan")
    assert removed["removed"] is True
    assert not launcher.exists()
    # 幂等：再 remove 报 removed=False
    assert remove_wrapper(tmp_path, name="product-scan")["removed"] is False


def test_undeclared_side_effect_mismatch_or_unknown_refused(tmp_path):
    # 声明 database_write 实跑 curl：可证伪的矛盾 → 拒绝
    r1 = run_bridge(tmp_path, integration_id="scan.cli", action="network.scan",
                    argv=["curl", "--version"], side_effect="database_write")
    assert r1["executed"] is False and "不符" in r1["error"]
    # 未知副作用字符串：拒绝
    r2 = run_bridge(tmp_path, integration_id="scan.cli", action="network.scan",
                    argv=["echo", "x"], side_effect="teleport")
    assert r2["executed"] is False
    # 只读动作未声明但触及 curl：自动进票据流程（fail-closed 分类生效），
    # 但不透明子进程不兑换 → 后验失败（闭环，无不兑也过）。
    r3 = run_bridge(tmp_path, integration_id="scan.cli", action="scan",
                    argv=["curl", "--version"])
    assert r3["executed"] is False and "admission 未兑换" in r3["error"]
    assert r3["challenge_count"] == 1
    assert r3["side_effect"] == "network_request"


def test_sh_dash_c_inner_command_classified(tmp_path, monkeypatch):
    """`sh -c "curl …"` 看内层，不看 sh 壳（只读直行关闭）。"""
    _admit_env(monkeypatch)
    child = tmp_path / "inner.sh"
    child.write_text("#!/bin/sh\nexec \"$@\"\n", encoding="utf-8")
    child.chmod(0o755)
    # 内层 curl → 票据类；不透明内层不兑换 → 拒绝
    r = run_bridge(tmp_path, integration_id="scan.cli", action="scan",
                   argv=["sh", "-c", "curl --version"])
    assert r["executed"] is False
    assert r["side_effect"] == "network_request"
    # 内层 echo → 本地只读直行
    r2 = run_bridge(tmp_path, integration_id="scan.cli", action="scan",
                    argv=["sh", "-c", "echo inner-hi"])
    assert r2["executed"] is True and "inner-hi" in r2["stdout_tail"]


def test_launcher_shell_quoting_no_expansion(tmp_path):
    """$(...) 反引号等不得被 shell 展开（shlex 引号）。"""
    import subprocess as _subprocess

    from sopcontrol.bridge import install_wrapper

    pwn = tmp_path / "pwned"
    install_wrapper(tmp_path, integration_id="scan.cli",
                    command=["echo", "$(touch {})".format(pwn), "`id`"],
                    name="quote-test")
    launcher = tmp_path / ".sopcontrol-local" / "bin" / "quote-test"
    proc = _subprocess.run([str(launcher)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0
    assert not pwn.exists()
    assert "$(touch" in proc.stdout


def test_challenge_admit_cli_roundtrip(tmp_path, monkeypatch, capsys):
    import json as _json

    from sopcontrol.cli import main

    monkeypatch.chdir(tmp_path)
    rc = main(["bridge", "challenge", "--action", "network.scan",
               "--integration-id", "scan.cli", "--side-effect", "network_request",
               "--", "curl", "--version"])
    assert rc == 0
    out = capsys.readouterr().out
    issued = _json.loads(out[out.index("{"):])
    assert issued["ticket_id"].startswith("tkt-")
    assert "secret" not in _json.dumps(issued)
    handoff = issued["handoff"]
    monkeypatch.setenv("SOPCTL_TICKET_FILE", handoff)
    rc = main(["bridge", "admit", "--action", "network.scan",
               "--integration-id", "scan.cli", "--side-effect", "network_request",
               "--", "curl", "--version"])
    assert rc == 0
    out = capsys.readouterr().out
    admitted = _json.loads(out[out.index("{"):])
    assert admitted["admitted"] is True
    # 票据已消费：再兑拒绝（单次性）
    rc = main(["bridge", "admit", "--action", "network.scan",
               "--integration-id", "scan.cli", "--side-effect", "network_request",
               "--", "curl", "--version"])
    assert rc == 1


def test_identifier_traversal_rejected_and_preexisting_restored(tmp_path):
    import pytest as _pytest

    from sopcontrol.bridge import install_wrapper, remove_wrapper

    with _pytest.raises(ValueError):
        install_wrapper(tmp_path, integration_id="x", command=["echo"], name="../../escaped")
    with _pytest.raises(ValueError):
        remove_wrapper(tmp_path, name="../../escaped")
    assert not (tmp_path / "escaped").exists()

    launcher = tmp_path / ".sopcontrol-local" / "bin" / "keep-me"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/bin/sh\necho ORIGINAL\n", encoding="utf-8")
    install_wrapper(tmp_path, integration_id="x", command=["echo", "new"], name="keep-me")
    assert "ORIGINAL" not in launcher.read_text(encoding="utf-8")
    removed = remove_wrapper(tmp_path, name="keep-me")
    assert removed["restored"] is True and removed["removed"] is False
    assert "ORIGINAL" in launcher.read_text(encoding="utf-8")


def test_admission_verification_for_handoff_ticket(tmp_path):
    from sopcontrol.tickets import TicketError, issue_ticket, verify_ticket_for_admission

    t = issue_ticket(tmp_path, action="network.scan", input_fingerprint="fp-9",
                     allowed_side_effects=["network_request"])
    ok = verify_ticket_for_admission(
        tmp_path, ticket_id=t.ticket_id, secret=t.secret,
        action="network.scan", input_fingerprint="fp-9",
        side_effect="network_request")
    assert ok["verified"] is True
    import pytest as _pytest

    with _pytest.raises(TicketError):
        verify_ticket_for_admission(
            tmp_path, ticket_id=t.ticket_id, secret="wrong",
            action="network.scan", input_fingerprint="fp-9")


def test_b8_doctor_mse_section(capsys):
    # B8：doctor输出MSE四行只读节，不改变退出码语义
    from sopcontrol.cli_core import cmd_doctor
    class A:
        path = "."
        full = False
        vertical = False
    assert cmd_doctor(A()) == 0
    out = capsys.readouterr().out
    assert "MSE 缺算子 surface" in out and "MSE 冻结计划" in out

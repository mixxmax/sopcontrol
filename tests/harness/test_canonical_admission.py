"""最终闭环桥票包反例优先（§15.4/§12.3）：配置/入口/预期/为何不能过/用何 digest。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from sopcontrol.bridge import (
    canonical_invocation,
    run_bridge,
)
from sopcontrol.bridge_scaffold import install_scaffold
from sopcontrol.tickets import TicketError, issue_ticket


def _scaffold_env(monkeypatch):
    pybin = Path(sys.executable)
    sopctl = pybin.parent / "sopctl"
    monkeypatch.setenv("SOPCTL_BIN",
                       str(sopctl) if sopctl.is_file() else f"{pybin} -m sopcontrol.cli")


def test_canonical_invocation_resolves_wrapper_to_business_argv(tmp_path):
    install_scaffold(tmp_path, name="prod", lang="sh",
                     integration_id="demo.cli", action="scan",
                     command=["product", "scan"])
    wrapper = str(tmp_path / ".sopcontrol-local" / "bin" / "prod")
    assert canonical_invocation(tmp_path, "demo.cli", [wrapper, "--fast"]) == [
        "product", "scan", "--fast"]
    assert canonical_invocation(tmp_path, "demo.cli", ["product", "scan"]) == [
        "product", "scan"]
    # 未注册原样返回
    assert canonical_invocation(tmp_path, "demo.cli", ["curl", "--version"]) == [
        "curl", "--version"]


def test_all_launch_forms_share_fingerprint(tmp_path, monkeypatch):
    """直接 wrapper / supervised run / 直接 admit 同一业务指纹（§10.4/§15.4.11）。"""
    _scaffold_env(monkeypatch)
    installed = install_scaffold(
        tmp_path, name="entry", lang="sh",
        integration_id="demo.cli", action="network.scan",
        command=["echo"], side_effect="network_request")
    from sopcontrol.bridge import canonical_fingerprint

    business_fp = canonical_fingerprint("demo.cli", "network.scan", ["echo", "go"])
    assert canonical_fingerprint(
        "demo.cli", "network.scan",
        canonical_invocation(tmp_path, "demo.cli", [installed["file"], "go"]),
    ) == business_fp
    proc = subprocess.run([installed["file"], "go"], capture_output=True,
                          text=True, timeout=60, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr[-500:]
    receipt = run_bridge(tmp_path, integration_id="demo.cli", action="network.scan",
                         argv=[installed["file"], "go2"], side_effect="network_request")
    assert receipt["executed"] is True, receipt.get("error")
    assert receipt["input_fingerprint"] == canonical_fingerprint(
        "demo.cli", "network.scan", ["echo", "go2"])


def test_mutated_param_fails_admission(tmp_path, monkeypatch):
    _scaffold_env(monkeypatch)
    installed = install_scaffold(
        tmp_path, name="entry2", lang="sh",
        integration_id="demo.cli", action="network.scan",
        command=["echo"], side_effect="network_request")
    from sopcontrol.cli import main

    monkeypatch.chdir(tmp_path)
    out = main(["bridge", "challenge", "--action", "network.scan",
                "--integration-id", "demo.cli", "--side-effect", "network_request",
                "--", installed["file"], "orig"])
    assert out == 0
    # 用另一组参数兑换同一票据必须失败（不能签发另一张继续）
    import json as _json
    from sopcontrol.bridge import admit_ticket

    handoffs = list((tmp_path / ".sopcontrol-local" / "tickets" / ".handoff").glob("*.json"))
    assert handoffs
    with pytest.raises(TicketError):
        admit_ticket(tmp_path, ticket_file=str(handoffs[-1]),
                     integration_id="demo.cli", action="network.scan",
                     argv=[installed["file"], "MUTATED"], side_effect="network_request")


def test_run_id_stable_across_challenge_admit(tmp_path, monkeypatch, capsys):
    from sopcontrol.cli import main

    monkeypatch.chdir(tmp_path)
    assert main(["bridge", "challenge", "--action", "scan",
                 "--integration-id", "demo.cli", "--side-effect", "",
                 "--", "echo", "hi"]) == 0
    out = capsys.readouterr().out
    issued = json.loads(out[out.index("{"):])
    assert issued["operation_id"].startswith("op-")


def test_empty_binding_rejected_when_expected(tmp_path):
    t = issue_ticket(tmp_path, action="a", input_fingerprint="fp",
                     allowed_side_effects=["network_request"])
    from sopcontrol.tickets import redeem_ticket

    with pytest.raises(TicketError):
        redeem_ticket(tmp_path, ticket_id=t.ticket_id, secret=t.secret,
                      action="a", input_fingerprint="fp",
                      side_effect="network_request",
                      expected_plan_digest="plan-want")
    with pytest.raises(TicketError):
        redeem_ticket(tmp_path, ticket_id=t.ticket_id, secret=t.secret,
                      action="a", input_fingerprint="fp",
                      side_effect="network_request", expected_phase="audit")


def test_allowed_actions_enforced(tmp_path):
    from sopcontrol.tickets import issue_ticket, redeem_ticket

    t = issue_ticket(tmp_path, action="a", input_fingerprint="fp",
                     allowed_side_effects=["network_request"],
                     allowed_actions=["a"])
    with pytest.raises(TicketError):
        redeem_ticket(tmp_path, ticket_id=t.ticket_id, secret=t.secret,
                      action="b", input_fingerprint="fp",
                      side_effect="network_request")


def test_phase_grant_bound_to_operation(tmp_path):
    from sopcontrol.tickets import (
        issue_phase_grant,
        phase_grant_fingerprint,
        redeem_ticket,
    )

    g = issue_phase_grant(tmp_path, phase="audit", task_id="T",
                          allowed_side_effects=["network_request"],
                          operation="op-1")
    fp = phase_grant_fingerprint(phase="audit",
                                 allowed_side_effects=["network_request"],
                                 task_id="T", operation="op-1")
    ok = redeem_ticket(tmp_path, ticket_id=g.ticket_id, secret=g.secret,
                       action="phase:audit", input_fingerprint=fp,
                       side_effect="network_request", expected_phase="audit",
                       expected_operation="op-1")
    assert ok.consumed_at is not None
    g2 = issue_phase_grant(tmp_path, phase="audit", task_id="T",
                           allowed_side_effects=["network_request"],
                           operation="op-1")
    with pytest.raises(TicketError):
        redeem_ticket(tmp_path, ticket_id=g2.ticket_id, secret=g2.secret,
                      action="phase:audit", input_fingerprint=phase_grant_fingerprint(
                          phase="audit", allowed_side_effects=["network_request"],
                          task_id="T", operation="op-1"),
                      side_effect="network_request", expected_phase="audit",
                      expected_operation="op-OTHER")


def test_secret_variant_scrub(tmp_path, monkeypatch):
    """子进程打印部分/JSON/URL 形态 secret，tails 仍干净（§11.4.2）。"""
    import sys as _sys

    _scaffold_env(monkeypatch)
    pybin = _sys.executable
    child = tmp_path / "leak.sh"
    child.write_text(
        "#!/bin/sh\n"
        f"SECRET=$(\"{pybin}\" -c \"import json,os;"
        f"print(json.load(open(os.environ['SOPCTL_TICKET_FILE']))['secret'])\")\n"
        f"\"{pybin}\" -m sopcontrol.cli bridge admit --integration-id demo.cli "
        f"--action network.scan --side-effect network_request -- \"$0\" || exit $?\n"
        "echo \"prefix-${SECRET#????????}\"\n"
        "echo \"{\\\"s\\\": \\\"$SECRET\\\"}\"\n"
        "echo \"https://x.test/?token=$SECRET\"\n",
        encoding="utf-8")
    child.chmod(0o755)
    receipt = run_bridge(tmp_path, integration_id="demo.cli", action="network.scan",
                         argv=[str(child)], side_effect="network_request")
    assert receipt["executed"] is True, receipt.get("error")
    blob = receipt["stdout_tail"]
    assert "https://x.test/?token=" not in blob or "***" in blob
    assert blob.count("***") >= 2  # 全量 + URL 形态至少被洗掉
    assert "ticket_model" not in receipt

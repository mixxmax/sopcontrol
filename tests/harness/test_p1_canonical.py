"""§9.5 必须添加的反例测试（Batch 4: Canonical Bridge 和 Scaffold）。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sopcontrol.bridge import (
    admit_ticket,
    canonical_fingerprint,
    canonical_invocation,
    challenge_admission,
    install_wrapper,
    operation_id,
    run_bridge,
    stable_run_id,
)
from sopcontrol.bridge_scaffold import install_scaffold
from sopcontrol.tickets import TicketError, redeem_ticket


def test_argv_token_boundaries_change_fingerprint():
    # 两个业务参数拼接后字符串相同，但 token 边界不同，指纹必须不同
    fp1 = canonical_fingerprint("test.cli", "echo", ["echo", "a b"])
    fp2 = canonical_fingerprint("test.cli", "echo", ["echo", "a", "b"])
    assert fp1 != fp2

    # 空参数与单空格参数指纹必须不同
    fp3 = canonical_fingerprint("test.cli", "echo", ["echo", ""])
    fp4 = canonical_fingerprint("test.cli", "echo", ["echo", " "])
    assert fp3 != fp4


def test_argv_special_characters_are_not_reparsed():
    # 参数中含有 shell 特殊符号，指纹直接反映 token 原文，不被 shell 重新解析
    special_args = ["echo", "hello; rm -rf /", "$VAR", "`date`", "a\nb", "quote'\""]
    fp = canonical_fingerprint("test.cli", "echo", special_args)
    assert fp.startswith("sha256:")

    # 修改任意字符，指纹必须改变
    modified_args = list(special_args)
    modified_args[1] = "hello; rm -rf / "
    assert canonical_fingerprint("test.cli", "echo", modified_args) != fp


def test_direct_wrapper_matches_bridge_fingerprint(tmp_path):
    # 安装透明 wrapper 后，直接执行 wrapper 还原的 business argv 指纹与 bridge 直接调用一致
    install_wrapper(tmp_path, integration_id="curl.cli", command=["curl", "-s", "https://api.test"])
    launcher_path = str(tmp_path / ".sopcontrol-local" / "bin" / "curl-cli-bridge")

    direct_argv = canonical_invocation(tmp_path, "curl.cli", [launcher_path, "--header", "X: 1"])
    expected_argv = ["curl", "-s", "https://api.test", "--header", "X: 1"]
    assert direct_argv == expected_argv
    assert canonical_fingerprint("curl.cli", "exec", direct_argv) == canonical_fingerprint("curl.cli", "exec", expected_argv)


def test_python_interpreter_matches_direct_wrapper(tmp_path):
    # python scaffold.py args... 与直接调用 scaffold.py 解析出的 canonical argv 一致
    install_scaffold(tmp_path, name="py-entry", lang="python", integration_id="scan.cli",
                     action="network.scan", command=["echo", "target"], side_effect="network_request")
    script_path = str(tmp_path / ".sopcontrol-local" / "bin" / "py-entry.py")

    direct = canonical_invocation(tmp_path, "scan.cli", [script_path, "arg1", "arg2"])
    via_python = canonical_invocation(tmp_path, "scan.cli", [sys.executable, script_path, "arg1", "arg2"])

    assert direct == ["echo", "target", "arg1", "arg2"]
    assert via_python == direct
    assert canonical_fingerprint("scan.cli", "network.scan", via_python) == canonical_fingerprint("scan.cli", "network.scan", direct)


def test_shell_wrapper_matches_direct_wrapper(tmp_path):
    # sh scaffold.sh args... 与直接调用 scaffold.sh 解析出的 canonical argv 一致
    install_scaffold(tmp_path, name="sh-entry", lang="sh", integration_id="scan.cli",
                     action="network.scan", command=["echo", "target"], side_effect="network_request")
    script_path = str(tmp_path / ".sopcontrol-local" / "bin" / "sh-entry")

    direct = canonical_invocation(tmp_path, "scan.cli", [script_path, "arg1"])
    via_sh = canonical_invocation(tmp_path, "scan.cli", ["/bin/sh", script_path, "arg1"])

    assert direct == ["echo", "target", "arg1"]
    assert via_sh == direct
    assert canonical_fingerprint("scan.cli", "network.scan", via_sh) == canonical_fingerprint("scan.cli", "network.scan", direct)


def test_node_wrapper_matches_direct_wrapper(tmp_path):
    # node scaffold.js args... 与直接调用 scaffold.js 解析出的 canonical argv 一致
    install_scaffold(tmp_path, name="js-entry", lang="node", integration_id="scan.cli",
                     action="network.scan", command=["echo", "target"], side_effect="network_request")
    script_path = str(tmp_path / ".sopcontrol-local" / "bin" / "js-entry.js")

    direct = canonical_invocation(tmp_path, "scan.cli", [script_path, "arg1"])
    via_node = canonical_invocation(tmp_path, "scan.cli", ["node", script_path, "arg1"])

    assert direct == ["echo", "target", "arg1"]
    assert via_node == direct
    assert canonical_fingerprint("scan.cli", "network.scan", via_node) == canonical_fingerprint("scan.cli", "network.scan", direct)


def test_nested_bridge_uses_business_argv(tmp_path):
    # wrapper 嵌套调用时，解析出的 canonical argv 必须是真正的底层业务命令，不能残留中间 wrapper
    install_wrapper(tmp_path, integration_id="inner.cli", command=["echo", "inner"], name="inner-bridge")
    inner_launcher = str(tmp_path / ".sopcontrol-local" / "bin" / "inner-bridge")
    install_wrapper(tmp_path, integration_id="outer.cli", command=[inner_launcher, "outer-fixed"], name="outer-bridge")
    outer_launcher = str(tmp_path / ".sopcontrol-local" / "bin" / "outer-bridge")

    resolved = canonical_invocation(tmp_path, "outer.cli", [outer_launcher, "user-arg"])
    assert resolved == ["echo", "inner", "outer-fixed", "user-arg"]


def test_python_scaffold_executes_with_side_effect(tmp_path, monkeypatch):
    # Python scaffold 实际执行（带副作用，先 challenge 获得 handoff，再由 scaffold 触发 admit 并执行命令）
    # 必须能正常运行，不得出现 NameError: name 'false' is not defined 等语法错误
    info = install_scaffold(tmp_path, name="py-side", lang="python", integration_id="test.py",
                            action="run.test", command=[sys.executable, "-c", "import sys; print('PY_EXEC_OK'); sys.exit(0)"],
                            side_effect="network_request")
    scaffold_path = Path(info["file"])
    assert scaffold_path.is_file()

    # 直接运行 python scaffold.py
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd())
    proc = subprocess.run([sys.executable, str(scaffold_path), "extra-arg"],
                          capture_output=True, text=True, cwd=str(tmp_path), env=env)
    assert proc.returncode == 0
    assert "PY_EXEC_OK" in proc.stdout


def test_python_scaffold_executes_readonly(tmp_path):
    # Python scaffold 只读运行，不产生 ticket 直接 exec
    info = install_scaffold(tmp_path, name="py-ro", lang="python", integration_id="test.py",
                            action="report", command=[sys.executable, "-c", "import sys; print('READONLY_OK'); sys.exit(0)"],
                            side_effect="")
    scaffold_path = Path(info["file"])
    assert scaffold_path.is_file()

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd())
    proc = subprocess.run([sys.executable, str(scaffold_path)],
                          capture_output=True, text=True, cwd=str(tmp_path), env=env)
    assert proc.returncode == 0
    assert "READONLY_OK" in proc.stdout


def test_parameter_mutation_rejects_old_ticket(tmp_path):
    # 为 argv1 申请票据后，如果试图将票据用于改变后的 argv2，必须因指纹不匹配被拒绝
    argv1 = ["echo", "original"]
    info = challenge_admission(tmp_path, integration_id="test.cli", action="network.scan",
                               argv=argv1, side_effect="network_request")

    argv2 = ["echo", "mutated"]
    with pytest.raises(TicketError, match="fingerprint mismatch"):
        admit_ticket(tmp_path, ticket_file=info["handoff"], integration_id="test.cli",
                     action="network.scan", argv=argv2, side_effect="network_request")


def test_operation_and_run_are_stable_across_retry():
    argv = ["curl", "-X", "POST", "https://example.com/api", "-d", '{"key": "value"}']
    op1 = operation_id("api.client", "network.post", argv)
    run1 = stable_run_id(op1)

    op2 = operation_id("api.client", "network.post", list(argv))
    run2 = stable_run_id(op2)

    assert op1 == op2
    assert run1 == run2
    assert op1.startswith("op-")
    assert run1.startswith("run-")


def _make_stub(tmp_path, name, body):
    stub = tmp_path / "bin" / name
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(body, encoding="utf-8")
    stub.chmod(0o755)
    return stub


def test_omitted_side_effect_external_tool_goes_challenge_not_direct_exec(tmp_path):
    # R-01/§7.2：已知网络工具（按名分类）side_effect 省略 → 必须走票据挑战，
    # 不得因“此次参数不联网”直接执行；子进程未 admit → executed=False。
    # 本测试用同名本地 stub，不触网。
    stub = _make_stub(tmp_path, "curl", "#!/bin/sh\necho local-stub\n")
    receipt = run_bridge(
        tmp_path, integration_id="scan.cli", action="network.scan",
        argv=[str(stub), "--version"],
    )
    assert receipt["challenge_count"] == 1
    assert receipt["side_effect"] == "network_request"
    assert receipt["executed"] is False
    assert "admission 未兑换" in receipt["error"]
    # R-04/§7.3：receipt 的 operation_id 与 ticket.operation 同源一致
    assert receipt["operation_id"] == receipt["ticket"]["operation"]


def test_operation_consistent_across_challenge_ticket_admit(tmp_path):
    # §7.3/R-09：challenge.operation_id = ticket.operation；capability_binding
    # 不一致拒绝、一致才兑换
    argv = ["curl", "https://example.invalid"]
    issued = challenge_admission(
        tmp_path, integration_id="scan.cli", action="network.scan",
        argv=argv, side_effect="network_request", task_id="TASK-X",
        capability_binding="bind-1",
    )
    assert issued["ticket"]["operation"] == issued["operation_id"]
    assert issued["ticket"]["run_id"] == issued["run_id"]
    assert issued["ticket"]["capability_binding"] == "bind-1"
    with pytest.raises(TicketError):
        admit_ticket(
            tmp_path, ticket_file=issued["handoff"], integration_id="scan.cli",
            action="network.scan", argv=argv, side_effect="network_request",
            task_id="TASK-X", capability_binding="bind-2",
        )
    ok = admit_ticket(
        tmp_path, ticket_file=issued["handoff"], integration_id="scan.cli",
        action="network.scan", argv=argv, side_effect="network_request",
        task_id="TASK-X",
    )
    assert ok["admitted"] is True


def test_run_bridge_receipt_carries_capability_binding(tmp_path):
    stub = _make_stub(tmp_path, "tool", "#!/bin/sh\necho ok\n")
    receipt = run_bridge(
        tmp_path, integration_id="local.cli", action="scan",
        argv=[str(stub)], capability_binding="bind-9",
    )
    assert receipt["executed"] is True
    assert receipt["capability_binding"] == "bind-9"


def test_install_scaffold_omitted_side_effect_never_bare_exec_external_tool(tmp_path):
    # R-01：curl 类集成 side_effect 省略 → 正式入口必须带 admit，不得裸 exec
    installed = install_scaffold(
        tmp_path, name="scan-entry", lang="sh", integration_id="scan.cli",
        action="network.scan", command=["curl", "--version"],
    )
    content = Path(installed["file"]).read_text(encoding="utf-8")
    assert "bridge admit" in content
    assert "readonly passthrough" not in content


def test_install_scaffold_cli_parity_with_api(tmp_path, monkeypatch):
    # §7.4：正式 CLI 与内部 API 得出相同分类
    from sopcontrol.cli import main

    monkeypatch.chdir(tmp_path)
    rc = main(["bridge", "install", "--action", "network.scan",
               "--integration-id", "scan.cli", "--lang", "sh",
               "--", "curl", "--version"])
    assert rc == 0
    content = (tmp_path / ".sopcontrol-local" / "bin" / "scan-cli-bridge").read_text(encoding="utf-8")
    assert "bridge admit" in content

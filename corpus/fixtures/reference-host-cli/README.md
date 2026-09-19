# Reference Host — CLI

> 这是本地参考宿主，明确不是 JobsFlow 证据，也不是任何真实业务系统。

这个 fixture 用一个很小的 CLI 暴露常见的宿主入口：

- `read`：直接读取文件；
- `status`：经 `sopcontrol.bridge.run_bridge` 执行的只读动作，预期零 ticket；
- `write`：外部写入动作，子进程先经 `bridge.admit` 兑换 handoff，再写入目标；
- `hook`：从 stdin 接收 JSON 的外部 hook；
- `fetch`：网络形状的高影响 stub，不触网，但必须完成 ticket admission。

## 运行

在仓库根目录执行。项目目录使用临时路径，避免把 fixture 的状态当成控制器证据：

```bash
PROJECT=/tmp/sop-reference-host-cli
.venv/bin/python -m sopcontrol.cli init "$PROJECT"
.venv/bin/python -m sopcontrol.cli attach "$PROJECT"
.venv/bin/python -m sopcontrol.cli attach-status "$PROJECT" --json

PYTHONPATH=. .venv/bin/python corpus/fixtures/reference-host-cli/host_cli.py \
  --project "$PROJECT" read README.md
PYTHONPATH=. .venv/bin/python corpus/fixtures/reference-host-cli/host_cli.py \
  --project "$PROJECT" status
PYTHONPATH=. .venv/bin/python corpus/fixtures/reference-host-cli/host_cli.py \
  --project "$PROJECT" write "$PROJECT/out.txt" 'controlled fixture write'
printf '{"argv":["true"],"action":"status"}\n' | \
  PYTHONPATH=. .venv/bin/python corpus/fixtures/reference-host-cli/host_cli.py \
  --project "$PROJECT" hook
PYTHONPATH=. .venv/bin/python corpus/fixtures/reference-host-cli/host_cli.py \
  --project "$PROJECT" fetch
```

预期形态是：`status` 返回 `executed: true` 且 `challenge_count: 0`；`write` 和
`fetch` 返回 `executed: true` 并带有 `redemption_point`。`fetch` 的
`network-shaped` 只是本地 stub，不代表真实网络已经被验证或允许。

## 与 SOP Control 的接线点

`write` 和 `fetch` 通过 `run_bridge` 生成 handoff；它们的内部子命令读取
`SOPCTL_TICKET_FILE`，调用 `admit_ticket`，然后才执行 fixture 内的本地动作。
这只证明合作式 adapter seam 可被调用。它不证明操作系统级隔离、恶意进程防护、
真实产品业务检查或 JobsFlow 接入。

`attach` / `attach-status` 是宿主接入演练；控制目录和回执均位于临时项目的
`.sopcontrol/` 或 `.sopcontrol-local/`，不应复制回仓库作为证据。

# Phase D — Controlled runtime (`sopctl enter`) (2026-09-09)

## Command

```bash
sopctl enter --path . --mode supervised -- -- <command...>
sopctl enter --path . --mode cooperative -- -- <command...>
sopctl enter --path . --mode testing --json -- -- true   # unit-test adapter
```

## Providers

| Mode | Production? | What it does | What it does *not* claim |
| --- | --- | --- | --- |
| `supervised` | yes | Spawns command, identity env, process spawn/child/exit events, receipt | File/network sandbox, unbypassable control |
| `cooperative` | yes | Identity env; expects harness-check reporting | Process tree, unbypassable control |
| `testing` | test only | Synthetic process events + receipt | Real subprocess |

HTTP_PROXY / env-only tricks are **not** treated as enforcement.

## Receipt

Written under `.sopcontrol-local/worktrees/<id>/runtime-receipts/<run_id>.json`.

Includes: run/project/worktree ids, capabilities, process events, honest gaps, `business_tree_damaged=false` on success path.

## Coverage

Surface `runtime_supervised` appears as observable with gap reason that file/network enforce are unsupported.

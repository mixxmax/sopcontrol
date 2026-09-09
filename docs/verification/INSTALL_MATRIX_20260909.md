# Install & upgrade matrix (Phase F)

## Supported

| Dimension | Values |
| --- | --- |
| Python | 3.10, 3.11, 3.12 (`requires-python >=3.10`) |
| OS | macOS (Darwin), Linux, Windows |
| Package | `pip install -e .` from a pinned commit, or PyPI `sopcontrol` when published |

Self-check:

```bash
sopctl compat
sopctl compat . --measure
```

## Harness expectations

| Harness | Expect | Do not claim |
| --- | --- | --- |
| OpenCode | Runtime plugin interception | — |
| Claude Code | PreToolUse via settings merge | Live without API key |
| Codex | Projection + `wrap` / `enter` + git/CI gate | Pre-tool runtime enforceable |

## Upgrade / downgrade

1. Pin a known-good commit (see `REPRODUCIBLE_VERSION.md` / release pins).
2. `pip install -e .` (or reinstall the pin) in the project or shared venv.
3. `sopctl compat .` then `sopctl attach .` (idempotent) then `sopctl doctor .`.
4. Downgrade: check out the older pin and reinstall; do not delete `.sopcontrol/` evidence.

## Detach

```bash
sopctl detach . --plan      # preview sopctl-owned hooks/plugins only
sopctl detach . --confirm   # remove those items; keep rules + evidence
```

## Perf budgets (soft)

| Metric | Budget |
| --- | --- |
| Cold `attach` P95 | ≤ 60s (no model calls) |
| Warm `attach-status` P95 | ≤ 2s |
| Warm `coverage` P95 | ≤ 5s |
| Fixture `gate` P95 | ≤ 30s |

## Offline / permission

- Offline: all default attach/coverage/gate paths are local; no network required.
- Permission denied on `.sopcontrol`: persist paths fail closed; `compat` reports writability issues when detectable.

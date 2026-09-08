# Phase A — Unified non-blocking attach (2026-09-08)

Implements Phase A of `docs/SOP_Control_全域无阻塞接入实施手册_2026-09-08.md`.

## Commands (now real)

```bash
sopctl attach .                 # plan + apply safe changes
sopctl attach . --plan          # read-only plan
sopctl attach . --mode observe  # same install path; no new enforced rules
sopctl attach-status .
sopctl detach . --plan          # preview-only removal list
```

## Behavior

- Orchestrates existing `init` / `identity` / `project all` / hook installers
- Does **not** auto-accept rules; does **not** call models
- Existing foreign `pre-push` → **chain** (backup + run previous then gate)
- Hook path via `git rev-parse --git-path` (worktree-safe)
- Corrupt Claude settings → defer Claude only; rest still connects
- Foreign OpenCode `sopcontrol.js` → isolate as `sopcontrol-attach.js`
- Non-git → identity + control dir; git surfaces marked unavailable
- Rollback receipt under `.sopcontrol-local/attachment/receipts/`

## Tests

```text
tests/attachment/test_plan.py
tests/attachment/test_apply.py
tests/attachment/test_idempotency.py
tests/attachment/test_existing_hooks.py
tests/attachment/test_non_git.py
tests/attachment/test_partial_failure.py
tests/attachment/test_rollback.py
```

## Out of scope (later phases)

- Action Plane / full tool ingest (Phase B)
- Control Coverage Ledger (Phase C)
- `sopctl enter` supervised runtime (Phase D)
- Network/browser/credential adapters (Phase E)

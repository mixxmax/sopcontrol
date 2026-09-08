# Prompt A — SOP Control final stabilization

## Root cause

Full-suite hang after ~558 passed (~85%, reported as ~77%):

`tests/harness/test_capability_fail_paths.py::test_capability_compare_offline`
called `sopctl capability-compare --live opencode`. On machines with
`opencode` on `PATH`, that spawned **three real live probes**
(`timeout_per_probe=180`) with captured output → **minutes of silence**
with no pytest progress.

Secondary silence risk: `sopctl metrics` → `mutation_enforcement()` nested
`pytest tests/corpus/test_mutations.py` (up to 300s) when invoked from a
test under the outer suite (`test_growth_refresh_status_inventory_explain`).

## Fixes

1. Offline compare test uses `--no-live --baselines-all` only.
2. `collect_live_probe_responses` refuses to spawn opencode under
   `SOPCONTROL_TEST_RUN_ACTIVE` unless a runner is injected; prints stage.
3. `mutation_enforcement` defers under the same guard; timeouts return
   structured failure (not hang).
4. `sopctl wrap` uses `subprocess.run(..., timeout=SOPCTL_WRAP_TIMEOUT)`.
5. Corpus shell steps timeout=60; git helpers in universal-plane tests timeout.
6. `conftest` prints `sopcontrol-test: START <nodeid>` on stderr for hang diagnosis.
7. Fixtures: subprocess timeout, multi-worktree, CLI-not-on-PATH, ticket
   expire/reuse/wrong-action (existing + extended), large/corrupt ledger
   (existing), large md repo (existing).
8. Reproducible version pins: `docs/verification/REPRODUCIBLE_VERSION.md`
   + `sopcontrol.__init__` schema exports.

## Acceptance (this delivery)

| Check | Result |
| --- | --- |
| Hang test offline | PASS (no opencode spawn) |
| Subprocess timeout fixtures | PASS |
| Multi-worktree / CLI-not-on-PATH | PASS |
| Ledger linear append / corrupt line | PASS |
| `sopctl doctor corpus/fixtures/shop-checkout` | PASS (~0.6s) |
| `sopctl gate corpus/fixtures/shop-checkout` | PASS (~1.5s, stage progress) |
| Full `pytest -q` | **661 passed, 1 skipped in 188.42s** (natural end; former hang test passed) |

## Compat

- Live capability compare still available via CLI for humans; unit tests
  must inject runners or `--no-live`.
- Metrics under pytest no longer nests mutation pytest (deferred note).
- Gate fail-closed strength unchanged.

## Pin

- Commit: `5bf6a6ec94cc167324c68cf01c43d47f59a7ce8d`
- Package / suggested tag: `0.2.0` / `v0.2.0`
- Not pushed (local branch only).

# Universal control plane — delivery report (2026-09-08)

## 1. Architecture & root cause

**Before:** `run_gate` always called full `run_audit` (all sensors). `DocScanSensor` used `limit=200` and raised `FileScanLimitExceeded` on large Markdown trees (JobsFlow ~14k `.md`), making **both discovery and gate unusable**. Pre-push hook was `exec sopctl` only (PATH-dependent). Worktree evidence lived in shared `.sopcontrol/evidence/`; identity hashed absolute path.

**After:**

| Layer | Behavior |
|-------|----------|
| `ProjectScope` | Git root / common-dir / worktree_id / HEAD / branch; rich `ScanCoverage`; discovery can **defer** past budget |
| `run_discovery` | Partial OK; grows candidates only; prints coverage |
| `run_enforcement` / `gate` | Accepted rules; source-unreadable → fail; md volume does not own the gate |
| Hook | `SOPCTL_BIN` → `.venv/bin/sopctl` → common-dir config → PATH → `python -m sopcontrol.cli`; never suggests `--no-verify` |
| Events | Versioned `ControlEvent` under `.sopcontrol-local/worktrees/<id>/` |
| Cache | `.sopcontrol-local/.../evidence-cache` (atomic); sensors not fully wired for hits yet |

## 2. Changed files (this delivery)

- `sopcontrol/context.py` — `ProjectScope`, `ScanCoverage`
- `sopcontrol/audit.py` — `run_discovery` / `run_enforcement`
- `sopcontrol/evidence_cache.py` — new
- `sopcontrol/resolve_cli.py` — new
- `sopcontrol/events.py` — new
- `sopcontrol/identity.py` — common-dir based `project_id`
- `sopcontrol/cli_common.py` — enforcement gate + hook template
- `sopcontrol/cli_core.py` / `cli.py` — audit `--enforce` / `--no-persist`; `event` CLI
- `plugins/sensors/doc_scan.py` — discovery budget defer; enforcement unlimited (bounded by gitignore/excludes)
- `tests/constitution/test_universal_plane.py` — new
- `examples/adapters/README.md` — adapter scaffold
- this report

## 3. Tests

```bash
pytest -q tests/constitution/test_universal_plane.py tests/constitution/test_scan_scope.py
# 25 passed (universal + scan_scope)
```

Covered: >1000 md defer, gitignore, discovery≠gate, source unreadable fail, consumer gap, cache hit/miss, hook resolver text, events, projection idempotent, event isolation.

## 4. JobsFlow read-only acceptance

**Target:** `/Users/xiezhijie/ai-job-search`  
**Note:** An early `sopctl audit` / `gate` with default persist wrote ledger/growth on JobsFlow (violates ideal zero-write). Subsequent timings used `persist=False` API. Prefer `sopctl audit --no-persist` going forward.

| Check | Result |
|-------|--------|
| `doctor` (light) | PASS (~1.0s) |
| discovery (`mode=discovery`) | PASS; `JF-PREVIEW-001` pass / wired_and_tested |
| coverage | eligible/scanned **234** (git tracked; ignores/dot dirs prune the ~14k md surface); complete=True |
| `gate` | PASS (0 fail / 0 gap) |
| `explain JF-PREVIEW-001` | PASS |

### Timings (API, `persist=False`)

| Pass | Seconds | Notes |
|------|---------|-------|
| discovery #1 | ~3.4s | coverage eligible=234 |
| enforcement | ~3.1s | JF-PREVIEW-001 pass |
| discovery #2 | ~3.3s | cache not yet sensor-wired (hits=0) |

CLI `gate` earlier wall ~146s (cold + persist path); warm API path is much faster.

## 5. Compatibility / migration

- Existing `.sopcontrol/` registries/tasks untouched by design.
- `ProjectContext` still works; prefer `ProjectScope`.
- `sopctl audit` default = **discovery**; `sopctl gate` = **enforcement**.
- Reinstall hooks: `sopctl hook install .` to pick up resolver script.
- Optional: set `SOPCTL_BIN` or worktree `.venv` for GUI Git.

## 6. Known limits

- Evidence **cache helpers exist** but most sensors do not yet call `EvidenceCache.get/put` (hits stay 0 until instrumented).
- Enforcement still runs full code sensors (correct for fail-closed completeness); large Python trees remain the main gate cost.
- JobsFlow private dirs rely on gitignore + scan_excludes + dot-dir prune — projects must declare `scan_excludes` for untracked data trees.
- Accidental persist during first JobsFlow CLI acceptance (see §4).

## 7. Commit

See git log after this delivery (local only; **not pushed**).

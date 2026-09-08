# P0/P1 hardening report — 2026-09-08

## Root cause analysis

| Symptom | Cause | Fix |
|---------|--------|-----|
| Gate hung minutes on JobsFlow ledger (~4.4MB / 4660 lines) | Each `append_evidence` called `_existing_ids()` → **full JSONL re-read** → O(n²) on persist | In-memory id cache + `append_many` under one lock |
| Corrupt lines invisible / silent skip | `_existing_ids` swallowed `JSONDecodeError` | `diagnose()` reports line+reason; append raises `LedgerError` |
| Gate silent for minutes | No stage progress | stderr progress: `gate: enforcement 开始`, `ledger[…]: append_many_*`, `gate: 审计完成 Xs` |
| Large md killed audit/gate | Shared path + doc_scan limit=200 | discovery defer vs enforcement (prior universal plane) + this ledger fix |
| Hook PATH fragility | bare `sopctl` | resolver chain (prior) kept |
| No capability ticket | missing | `sopcontrol/tickets.py` + `sopctl ticket issue\|redeem` |

## Changed files

- `sopcontrol/ledger.py` — id cache, `append_many`, `diagnose`, `LedgerError`
- `sopcontrol/audit.py` — batch persist + progress
- `sopcontrol/cli_common.py` — gate stage progress + ledger error hints
- `sopcontrol/tickets.py` — new one-shot capability tickets
- `sopcontrol/cli_core.py` / `cli.py` — `ledger diagnose`, `ticket issue|redeem`
- `tests/constitution/test_ledger.py` — perf + corruption line
- `tests/constitution/test_universal_plane.py` — ticket expiry/reuse/mismatch
- this report

## Tests

```bash
pytest -q tests/constitution/test_ledger.py tests/constitution/test_universal_plane.py
# 25 passed
```

Includes: concurrent append, append_many linearity (<2s for +400 on 400-seed), corruption line report, ticket expire/reuse/secret/action mismatch, >1000 md discovery defer, etc.

## Performance

| Operation | Before (conceptual) | After (measured) |
|-----------|---------------------|------------------|
| append 2000 onto 2000-line ledger | O(n²) full re-reads (~minutes at JobsFlow scale) | **~7ms** `append_many` |
| JobsFlow `audit --no-persist` | previously could raise on md limit / hang on persist | **~5.1s**, mode=discovery, JF-PREVIEW pass |
| JobsFlow enforcement API no-persist | — | **~5.0s**, pass |
| JobsFlow `doctor` light | — | **~1.2s** |

## API / schema changes

| Surface | Change |
|---------|--------|
| `Ledger.append_many` | new |
| `Ledger.diagnose` | new structured report |
| `LedgerError` | path + line |
| `sopctl ledger diagnose` | new CLI |
| `sopctl ticket issue\|redeem` | new; secret printed once on issue |
| `CapabilityTicket` | schema_version=1; secret not forgeable via env |
| `sopctl audit --no-persist` | readonly audit (no ledger/growth write) |

## Compatibility

- Existing ledgers load unchanged; first append rebuilds id cache.
- Corrupt ledger: append/diagnose fail loud; repair via `audit --compact` (explicit).
- Tickets/events/cache stay under `.sopcontrol-local/` (gitignored).
- Reinstall hooks if needed: `sopctl hook install .`

## JobsFlow read-only acceptance

**Zero write path used:** `doctor`, `audit --no-persist`, `ledger diagnose`, enforcement API `persist=False`.

| Check | Result |
|-------|--------|
| doctor | PASS |
| audit --no-persist | discovery; coverage eligible=238; JF-PREVIEW-001 **pass** |
| ledger diagnose | ok=True, 4660/4660 valid |
| enforcement no-persist | JF-PREVIEW-001 **pass** |
| No JobsFlow private content copied into sopcontrol repo | yes |

## Known limits

- Sensor-level cache hit path still optional (helpers exist; not all sensors call get/put).
- `sopctl gate` still persists by design (push door); use enforcement API / future `--no-persist` on gate if needed for dry runs.
- Gate wall time still dominated by code AST sensors on large trees, not ledger.

## Commit

See `git log -1` after this delivery (**not pushed**).

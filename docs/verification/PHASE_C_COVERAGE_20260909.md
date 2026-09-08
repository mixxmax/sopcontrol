# Phase C — Control Coverage Ledger (2026-09-09)

## Commands

```bash
sopctl coverage .
sopctl coverage . --json
sopctl coverage . --probe filesystem_write
```

## Metrics (kept separate)

| Metric | Meaning |
| --- | --- |
| `scan_coverage` | Static eligible/scanned files (`ProjectScope`) |
| `connection_coverage` | Identity / control dir / hook / harness readiness |
| `control_coverage` | Runtime surfaces: detected → observable → enforceable → **verified** |

**Verified requires a penetration probe.** Adapter self-report alone cannot produce 100%.

## Surface states

`undiscovered` · `detected` · `observable` · `enforceable` · `verified` · `gap` · `unsupported`

New unknown tools expand the denominator (`unknown:<name>`). Removing an adapter expires prior verified probes for that surface.

## Files

- `sopcontrol/coverage_model.py`
- `sopcontrol/coverage.py`
- `sopcontrol/coverage_probe.py`
- `sopcontrol/cli_coverage.py`
- `tests/harness/test_coverage.py`

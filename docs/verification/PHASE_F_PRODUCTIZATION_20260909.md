# Phase F — Productization (2026-09-09)

## Delivered

| Item | Location |
| --- | --- |
| Install matrix | `docs/verification/INSTALL_MATRIX_20260909.md`, `sopcontrol/product.py` |
| `sopctl compat` | platform / harness / perf budgets (+ `--measure`) |
| `sopctl detach --confirm` | remove sopctl-owned hooks/plugins; keep rules/evidence |
| README / LIMITATIONS / RESIDUAL_RISKS / CHANGELOG | real A–F commands only |
| Perf budget tests | `tests/harness/test_product_phase_f.py` |

## Commands

```bash
sopctl compat
sopctl compat . --json --measure
sopctl detach . --plan
sopctl detach . --confirm
```

## Honest residuals added

- R12: supervised runtime is not a sandbox
- R13: effect primitives are not product breakers

# Release pin — 2026-09-08

## Recommended product SHA

```
f568a29f50abdd3722ff16e25c0e17348de50e16
```

External projects (including JobsFlow) should pin this commit.

## Functional delta since previous product pin `5bf6a6e`

| SHA | Type | Include in product? |
| --- | --- | --- |
| `5bf6a6e` | Previous pin (pytest hang / offline capability-compare) | Baseline |
| `3e148c1` | Docs only | Optional |
| **`f568a29`** | **Ledger `replace_snapshot` / `audit --compact` id dedupe; doctor issue kinds** | **Required** |
| Later docs commits | Docs only | Optional (pin file clarity) |

### Why `f568a29` is required

Without compact-time id dedupe, sensors may emit the same content-addressed `evidence_id` more than once in one audit round. `audit --compact` previously wrote those duplicates into the ledger; `gate` then fail-closed on `duplicate_id`. Compact is the documented repair path — it must leave a verifiable ledger.

This is generic control-plane behavior, not a JobsFlow hardcode.

## What this release does *not* change

- No JobsFlow business code
- No lowering of gate fail-closed strength
- No deletion of historical evidence as part of the pin (consumer projects refresh via `sopctl audit --compact` themselves)

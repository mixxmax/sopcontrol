# SOP Control — reproducible version identity

Do not put developer-personal absolute paths in install recipes or CI.

## Product pin (external projects)

| Field | Value |
| --- | --- |
| **Recommended pin (SHA)** | `f568a29f50abdd3722ff16e25c0e17348de50e16` |
| Short | `f568a29` |
| Subject | `[fix] compact ledger dedupes evidence ids so gate can pass after repair` |
| Suggested tag | `v0.2.0` (package version; create tag on the pin when publishing) |
| Package version | `0.2.0` (`sopcontrol.__version__` / `pyproject.toml`) |
| Public API surface | CLI `sopctl` + importable `sopcontrol.*` (0.2 series) |
| Capability ticket schema | `1` (`sopcontrol.tickets.SCHEMA_VERSION`) |
| Control event schema | `1` (`sopcontrol.events.SCHEMA_VERSION`) |
| Capability event schema | `2` (`CapabilityEvent.schema_version`, loads v1) |

Pin **`f568a29`**, not an older hang-fix-only tip. Docs-only commits after this SHA do not change runtime behavior.

### Why not stay on `5bf6a6e`?

| Commit | Kind | Product impact |
| --- | --- | --- |
| `5bf6a6e` | fix | Hang-fix for full pytest / live capability-compare offline; **previous product pin** |
| `3e148c1` | docs | Pin documentation only |
| **`f568a29`** | **fix** | **`audit --compact` dedupes evidence ids** so `gate` can pass after repair when sensors emit duplicate content-addressed rows |
| `cdbb14c`+ | docs | Pin documentation only |

**Must include `f568a29` in product.** Without it, a project that runs `sopctl audit --compact` then `sopctl gate` can still be blocked on `duplicate_id` even though compact is the documented repair path. That is a control-plane correctness bug, not a JobsFlow-specific quirk.

### Install at the pin

```bash
python3 -m venv .venv
.venv/bin/pip install -e "git+https://github.com/mixxmax/sopcontrol.git@f568a29f50abdd3722ff16e25c0e17348de50e16#egg=sopcontrol"
# or from a local clone checked out at that commit:
git checkout f568a29f50abdd3722ff16e25c0e17348de50e16
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Hook resolve (venv not required)

1. Prefer `SOPCTL_BIN` pointing at an executable `sopctl`
2. Else worktree `.venv/bin/sopctl`
3. Else git-common-dir `.sopcontrol-local/sopctl-bin` pointer
4. Else `PATH`
5. Else `python -m sopcontrol.cli`

Do not use `--no-verify` to bypass hooks.

## Bootstrap a new clone

```bash
git clone <sopcontrol-url>
cd sopcontrol
git checkout f568a29f50abdd3722ff16e25c0e17348de50e16
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/sopctl doctor .
.venv/bin/sopctl gate .
```

For a *consumer* project:

```bash
cd your-project
python3 -m venv .venv
.venv/bin/pip install -e path/to/sopcontrol   # checkout at f568a29
.venv/bin/sopctl init .
.venv/bin/sopctl hook git .    # installs fail-closed pre-push
.venv/bin/sopctl doctor .
```

## Compat notes (0.2)

- Discovery incompleteness does not fail the enforcement gate.
- Large Markdown trees are no longer hard-capped at 200 files for discovery; enforcement still fail-closes on accepted rule source/consumer/test gaps.
- Ledger append uses an id cache / `append_many` (not O(n²) full re-read per row).
- **`replace_snapshot` / `audit --compact` writes unique evidence/finding ids** (first-seen wins); `gate.verify` still fail-closes on remaining duplicates or corrupt lines.
- Corrupt ledger lines report path + line via `sopctl ledger diagnose`.
- Live capability probes must not run inside unit tests; use injected runners or `--no-live`.

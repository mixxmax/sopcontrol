# SOP Control — reproducible version identity

Do not put developer-personal absolute paths in install recipes or CI.

## Identity (fill at release / pin from `git rev-parse HEAD`)

| Field | Value |
| --- | --- |
| Git commit | `a8f176d3c2be1430f0c782b57e5854762afedc11` |
| Suggested tag | `v0.2.0` (matches package version) |
| Package version | `0.2.0` (`sopcontrol.__version__` / `pyproject.toml`) |
| Public API surface | CLI `sopctl` + importable `sopcontrol.*` (0.2 series) |
| Capability ticket schema | `1` (`sopcontrol.tickets.SCHEMA_VERSION`) |
| Control event schema | `1` (`sopcontrol.events.SCHEMA_VERSION`) |
| Capability event schema | `2` (`CapabilityEvent.schema_version`, loads v1) |

## Install (portable)

```bash
python3 -m venv .venv
.venv/bin/pip install -e path/to/sopcontrol
# or from a clone of this repo:
.venv/bin/pip install -e .
```

Hook / GUI / CI without activating the venv:

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
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/sopctl doctor .
.venv/bin/sopctl gate .
```

For a *consumer* project:

```bash
cd your-project
python3 -m venv .venv
.venv/bin/pip install -e path/to/sopcontrol
.venv/bin/sopctl init .
.venv/bin/sopctl hook git .    # installs fail-closed pre-push
.venv/bin/sopctl doctor .
```

## Compat notes (0.2)

- Discovery incompleteness does not fail the enforcement gate.
- Large Markdown trees are no longer hard-capped at 200 files for discovery; enforcement still fail-closes on accepted rule source/consumer/test gaps.
- Ledger append uses an id cache / `append_many` (not O(n²) full re-read per row).
- Corrupt ledger lines report path + line via `sopctl ledger diagnose`.
- Live capability probes must not run inside unit tests; use injected runners or `--no-live`.

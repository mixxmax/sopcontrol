# Changelog

## Unreleased

### Added

- Universal attach handbook Phases A–F: `attach` / `coverage` / `enter` / `effect` / `compat` / `detach --confirm` (see `docs/verification/PHASE_*` and `INSTALL_MATRIX_20260909.md`)
- Universal control plane: `ProjectScope` + discovery/enforcement split; worktree-local evidence cache & events; hook CLI resolver; `sopctl audit --enforce` / `--no-persist`; `sopctl event` (see `docs/verification/UNIVERSAL_PLANE_20260908.md`)
- P0/P1 hardening: ledger id-cache + `append_many` (kill O(n²) persist); `sopctl ledger diagnose`; gate stage progress; one-shot `sopctl ticket issue|redeem` (see `docs/verification/P0P1_HARDENING_20260908.md`)

## 0.2.0 — 2026-09-06

First public-facing packaging of the living-project control plane.

### Added

- Living project loop: projection slices with chain-head budget & session recovery protocol, chronicle (`project-events.jsonl` + `sopctl chronicle check|snapshot`), ambient growth, space measure (`growth measure|diff`)
- Reversible rule lifecycle: `rule suspend --until` / `reinstate` / `narrow --scope` — content-addressed two-phase human confirmation, inclusive deadline (`at <= until` paused, `at > until` auto-recovers), path-scope v1 (project or repo-relative prefixes) enforced across audit, verdicts, conflicts, maturity, tasks, repair and projections
- Permanent exits: `rule deprecate` / `rule supersede` (supersede atomically accepts proposed replacements; replacement must cover the retiring scope)
- `task withdraw` — unaccepted contract proposals exit legally to a terminal state (repair tasks refused; reason required; envelope + chronicle leave a paper trail)
- Evidence lifecycle binding: attestations bind to the current lifecycle revision (agent self-signature refused; sources must be in-repo regular files), trace freshness checked per guard (stale / future / naive rejected)
- Mid-conversation model switch: `task rebind` (permissions only tighten), harness executor identity guard
- Disambiguation: `redundant_entry_point`, `candidate enact` → bounded delete-entry tasks; retire-rule candidates materialize after sustained multi-round evidence (human two-phase exit only — never automatic)
- Dual-language README lifecycle/withdraw parity; combined statement+branch coverage enforced at >=85% (`fail_under`), with branch coverage reported separately
- Verification artifacts: product red-team checklist + first report; product verification simulation (`docs/verification/`)

### Fixed

- Governance facts single-entry: ordinary `Registry.save/add/transition` cannot inject, rewrite, delete or restore retirement / lifecycle / attestation facts; duplicate rule IDs rejected before write
- Concurrency safety: registry-wide reentrant RLock + cross-process `flock` on canonical paths with atomic temp-file writes; ledger RLock + `flock` with atomic `replace_snapshot`; task check-to-save and repair check-to-copy share the registry lock
- Symlink TOCTOU closures: attestation hashes an `O_NOFOLLOW`-opened fd; repair copies via dirfd + `O_NOFOLLOW`
- Projection energy-cap warning now lands inside the managed section — `project all -> check` converges beyond budget; retire-candidate fingerprints are round-count stable (aggregation, not proliferation)
- Audit completeness/atomicity verified from a clean controller baseline
- Scan traversal excludes `.worktrees` / `.dsh` / `.pnpm-store` / `.planning` so the 500-file cap does not hide main-tree consumers

### Energy

- `sopctl doctor` defaults to **light** (space snapshot + next moves; no full-tree inventory/audit); use `--full` when needed
- Projection section fitted to <=~1500 tokens / 80 lines; pending candidates ranked delete/improve before `register_rule`; warn when observed candidates > 32
- **Next-move (mid-session)**: `sopctl doctor` ends with up to 3 executable next steps (arm / real rule / enact-absorb-retire)
- **Deliver space frame**: `task deliver` captures a full growth snapshot and narrates whether the ambiguity space narrowed

### Notes

- Still **experimental**. Authority stays in `.sopcontrol/`; candidates never auto-promote; permanent exits remain human two-phase.
- Not published to PyPI yet; install from git (see README).

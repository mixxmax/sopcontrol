# Changelog

## 0.4.1 — 2026-09-26 (Beta / early public)

Pre-launch hardening. Upgrade from 0.4.0 is recommended: the bypasses below
work against 0.4.0.

### Security

- **Discuss-only lock covers the shell**: while the session intent is `discuss_only`, Bash only runs a read-only allow-list (`ls`, `cat`, `grep`, `git status/diff/log`, read-only `sopctl` queries, …). Command chains, substitution, subshells and embedded newlines are parsed rather than trusted; anything unprovable is refused.
- **Agents cannot lift or forge the user's intent**: `sopctl intent clear` and `sopctl intake --conversation` issued through an agent tool call are refused (`GUARD-INTENT-DISCUSS-ONLY`); a human runs them in a terminal.
- **The pre-push gate cannot be removed or skipped from the shell**: Bash that changes `.git/hooks`, any command that sets `core.hooksPath`, and Write/Edit on files under `.git/hooks/` are refused (`GUARD-SELF-UNINSTALL`).
- **Every spelling of push reaches the gate**: push detection parses the command (`git -C . push`, `/usr/bin/git push`, `command git push`, `sh -c 'git push'`) instead of matching the literal `git push`.

### Added

- `scripts/demo.sh`: a 60-second, model-free demo that feeds `sopctl` real Claude Code PreToolUse payloads and exits non-zero on any unexpected decision; run in CI. `scripts/demo.tape` records it with vhs.
- README five-minute start (Chinese and English) and launch drafts under `docs/launch/`.

### Status

- Beta / early public — not GA; platform matrix and sandbox limits unchanged (LIMITATIONS.md)

## 0.4.0 — 2026-09-14 (Beta / early public)

### Added / Fixed

- Learn/dynamic permanent decisions require user confirmation envelopes (`actor=user` alone is not consent)
- Review windows isolate by original task/session (no cross-task pollution)
- `once_only` durability blocks control promotion into permanent registry
- Activity log / run report loop (`sopctl log list|show|report|health`) under `.sopcontrol-local/`
- JobsFlow vendor pin/manifest tooling for reproducible 0.4.0 snapshots

### Status

- Beta / early public — not GA
- Platform matrix and sandbox limits unchanged; see LIMITATIONS.md


## 0.3.1 — 2026-09-14

PROMPT-D fix pack: dynamic SOP control route closes the confirm/compile loop.

### Fixed

- **DS-05**: `learn decide --route control|both` now auto-runs `confirm_candidate(keep_longterm)` + `compile_rule` after CandidateStore upsert, so user confirmation enters effective/selectable rules (not candidate-only)
- **DS-04**: `once_only` route records session-level evidence and never grows permanent Registry
- **LR-01/02/06**: `FakeDistiller` (alias `DeterministicRuleExtractor`) honestly named; refuses chitchat/system-error topics; once-only evidence is not recommended as `permanent_candidate`

### Verification

- Dynamic/learning regression: control → compiled + select; reload; idempotent rule_id; chitchat/system-error zero proposals

## 0.3.0 — 2026-09-09

Universal attach control plane + segmentation release (Early Access). Audit baseline: `f65b191`.

### Added

- Universal attach handbook Phases A–F: `attach` / `coverage` / `enter` / `effect` / `compat` / `detach --confirm` (see `docs/verification/PHASE_*` and `INSTALL_MATRIX_20260909.md`)
- Universal control plane: `ProjectScope` + discovery/enforcement split; worktree-local evidence cache & events; hook CLI resolver; `sopctl audit --enforce` / `--no-persist`; `sopctl event` (see `docs/verification/UNIVERSAL_PLANE_20260908.md`)
- **下一刀（中途接入）**: `sopctl doctor` 末尾最多 3 步可执行下一步（武装 / 真规则 / enact·吸收·退场）
- **deliver 空间帧**: `task deliver` 成功后自动 `growth` 全量快照 + 对照上一帧变窄叙事（编年 `growth.deliver_measure`）
- **久悬 gap**: `documented_rule_no_consumer` 等 → `improve_entry`；约 6 轮仍缺消费者 → 额外 `retire_rule` 候选（仅建议 `rule suspend` / `deprecate`，不自动退场）
- Scan honors git boundaries: dot-directories pruned as tool state; manifest `scan_excludes` for data directories; over-limit still fails loud

### Fixed

- REL-001: `cli_product` missing `sys` import — over-budget warnings now print instead of NameError (with regression tests)
- REL-002: coverage combine INTERNALERROR (statement/branch mix from subprocess measurement) — release verification command unified on `--cov-branch` so main and child processes agree
- REL-004: hook resolver python fallbacks no longer swallow the fail-closed install hint when the module import fails (importability pre-check on both fallbacks)
- Scan traversal excludes `.worktrees` / `.dsh` / `.pnpm-store` / `.planning` so the 500-file cap does not hide main-tree consumers

### Energy

- `sopctl doctor` defaults to **light** (space snapshot + next moves; no full-tree inventory/audit); use `--full` when needed
- Projection section fitted to ≤~1500 tokens / 80 lines; pending candidates ranked delete/improve before `register_rule`; warn when observed candidates > 32

### Verification

- Product red-team checklist + first report (`docs/verification/REDTEAM_CHECKLIST.md`, `REDTEAM_20260902.md`)
- Product verification simulation (`docs/verification/SIM_20260902T071439Z.md`)

### Docs

- Dual-language README (EN + ZH) with reversible lifecycle, withdraw and coverage-gate parity
- JobsFlow enablement kit (`docs/onboarding/JOBSFLOW_ENABLEMENT.md`)

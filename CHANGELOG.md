# Changelog

## 0.4.0

- Learn/dynamic permanent decisions require user confirmation envelopes
- Review windows isolate by original task/session
- once_only durability blocks control promotion
- Release codename / workspace target: 0.4.0


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
